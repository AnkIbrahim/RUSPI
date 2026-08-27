"""Fonctions vocales pour l'assistant R.U.S.P.I.

Ce module gère :
- l'enregistrement audio depuis le micro,
- la transcription locale via faster-whisper,
- la synthèse vocale via edge-tts,
- la lecture du son généré.

Le chargement du modèle Whisper est fait une seule fois, au niveau du module,
ce qui évite de recharger le modèle à chaque appel.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import threading
import time
import wave
from pathlib import Path

_WHISPER_MODEL = None

# Variables globales pour gérer la pause/reprise de l'écoute continue.
# Utilisées pour éviter la latence causée par la compétition audio entre
# l'entrée (micro) et la sortie (synthèse vocale).
_FLUX_ECOUTE_CONTINUE = None
_EVENEMENT_PAUSE_ECOUTE = None

# État partagé de la lecture MCI, consulté par le bouton d'arrêt de la GUI.
# L'alias doit être unique par lecture pour éviter les collisions MCI et le
# code 263 (MCIERR_INVALID_DEVICE_NAME) lorsque plusieurs lectures se suivent.
_VERROU_LECTURE = threading.Lock()
_WINMM_LECTURE = None
_LECTURE_EN_COURS = False
_ALIAS_LECTURE = "ruspi_audio"
_ALIAS_LECTURE_ACTIF = None
_EVENEMENT_ARRET_LECTURE = threading.Event()


def _configurer_mci_send_string(winmm) -> None:
    """Déclare la signature Unicode exacte de mciSendStringW via ctypes."""
    import ctypes

    # Forcer les types Win32 évite une conversion ambiguë des commandes Unicode.
    winmm.mciSendStringW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    winmm.mciSendStringW.restype = ctypes.c_uint

# Phrases souvent produites par Whisper lorsqu'il n'y a pas de parole.
HALLUCINATIONS_WHISPER = [
    "Sous-titres réalisés par la communauté d'Amara.org",
    "Merci d'avoir regardé cette vidéo",
    "Abonnez-vous à la chaîne",
    "Sous-titres réalisés par la communauté",
]


def _charger_modele_whisper():
    """Charge le modèle Whisper une seule fois et le retourne."""
    global _WHISPER_MODEL

    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL

    try:
        from faster_whisper import WhisperModel
    except ImportError as erreur:
        raise RuntimeError(
            "La reconnaissance vocale n'est pas disponible : la librairie 'faster-whisper' manque. "
            "Installez les dépendances du projet avant d'utiliser la commande 'vocal'."
        ) from erreur

    try:
        # Le modèle 'small' offre une meilleure précision que 'base',
        # notamment sur les noms propres, pour un coût en performance modéré.
        _WHISPER_MODEL = WhisperModel("small", device="cpu", compute_type="int8")
    except Exception as erreur:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            "Le modèle de transcription vocale n'a pas pu être chargé. Vérifiez votre installation de faster-whisper."
        ) from erreur

    return _WHISPER_MODEL


def pause_ecoute_continue() -> None:
    """Met en pause temporairement l'écoute continue sans la fermer.
    
    Utile pour éviter la latence et la compétition audio quand R.U.S.P.I doit parler
    pendant que le mode mains libres est actif.
    N'affecte pas le micro classique (bouton "🎤 Parler").
    """
    global _EVENEMENT_PAUSE_ECOUTE
    if _EVENEMENT_PAUSE_ECOUTE is not None:
        print("[DEBUG] pause_ecoute_continue() : mise en pause de l'écoute")
        _EVENEMENT_PAUSE_ECOUTE.set()
    else:
        print("[DEBUG] pause_ecoute_continue() : _EVENEMENT_PAUSE_ECOUTE est None")


def reprendre_ecoute_continue() -> None:
    """Reprend l'écoute continue après une pause.
    
    Remet le flux audio en état d'écoute active.
    """
    global _EVENEMENT_PAUSE_ECOUTE
    if _EVENEMENT_PAUSE_ECOUTE is not None:
        print("[DEBUG] reprendre_ecoute_continue() : reprise de l'écoute")
        _EVENEMENT_PAUSE_ECOUTE.clear()
    else:
        print("[DEBUG] reprendre_ecoute_continue() : _EVENEMENT_PAUSE_ECOUTE est None")


def arreter_lecture_en_cours() -> None:
    """Demande l'arrêt de la lecture au thread qui possède le périphérique MCI."""
    if not _LECTURE_EN_COURS:
        print("[DEBUG] arreter_lecture_en_cours() : aucune lecture active.")
        return

    # Aucun appel MCI ne doit partir du thread Tkinter : le thread audio
    # effectuera le « stop » sur le périphérique qu'il a lui-même ouvert.
    print("[DEBUG] arreter_lecture_en_cours() : demande d'arrêt transmise au thread audio.")
    _EVENEMENT_ARRET_LECTURE.set()


def _audio_en_numpy(audio):
    """Convertit le flux audio en tableau NumPy mono, compatible WAV."""
    import numpy as np

    tableau = np.asarray(audio)
    if tableau.ndim > 1:
        tableau = np.mean(tableau, axis=1)
    tableau = np.clip(tableau, -1.0, 1.0)
    return tableau.astype(np.float32)


def _ecrire_wav_depuis_numpy(nom_fichier: str, audio, frequence: int = 16000) -> None:
    """Écrit un fichier WAV à partir d'un tableau audio NumPy."""
    import numpy as np

    tableau = _audio_en_numpy(audio)
    pcm = (tableau * 32767).astype(np.int16)

    with wave.open(nom_fichier, "wb") as fichier_wav:
        fichier_wav.setnchannels(1)
        fichier_wav.setsampwidth(2)
        fichier_wav.setframerate(frequence)
        fichier_wav.writeframes(pcm.tobytes())


def _texte_est_hallucination(texte: str) -> bool:
    """Indique si Whisper a probablement inventé du texte sur du bruit."""
    texte_minuscule = texte.lower()
    return any(
        hallucination.lower() == texte_minuscule
        or hallucination.lower() in texte_minuscule
        for hallucination in HALLUCINATIONS_WHISPER
    )


def ecouter_micro(duree_secondes: int = 6) -> str:
    """Enregistre le micro, le transcrit en français, puis retourne le texte.
    
    Détecte aussi :
    - Le silence complet (niveau sonore RMS très bas)
    - Les hallucinations typiques de Whisper (phrases générées sur du silence)
    """
    if duree_secondes <= 0:
        raise ValueError("La durée d'enregistrement doit être supérieure à 0 seconde.")

    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as erreur:
        raise RuntimeError(
            "L'enregistrement vocal n'est pas disponible : la librairie 'sounddevice' ou 'numpy' manque."
        ) from erreur

    frequence = 16000
    fichier_wav = None

    try:
        try:
            # Vérification très simple: si le périphérique audio est inaccessible,
            # on remonte une erreur claire à l'utilisateur.
            sd.query_devices()
        except Exception:
            pass

        # On laisse un très court délai pour que l'utilisateur ait le temps de
        # commencer à parler après avoir vu le message d'invitation.
        time.sleep(0.5)

        # Enregistrement pendant une durée légèrement plus généreuse.
        audio = sd.rec(
            frames=int(frequence * duree_secondes),
            samplerate=frequence,
            channels=1,
            dtype="float32",
        )
        sd.wait()

        if audio.size == 0:
            raise RuntimeError("Le microphone n'a renvoyé aucun son.")

        # Calcul du niveau sonore moyen (RMS = Root Mean Square) pour détecter le silence
        import numpy as np
        rms = float(np.sqrt(np.mean(audio ** 2)))

        # Si le niveau est très faible (silence quasi total), rejeter sans transcrire
        # Un RMS < 0.01 indique généralement du silence ou du bruit ambiant très faible
        if rms < 0.01:
            raise RuntimeError(
                "Aucune parole détectée (silence détecté). Veuillez réessayer et parler "
                "plus fort ou plus près du microphone."
            )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fichier_temp:
            fichier_wav = fichier_temp.name

        _ecrire_wav_depuis_numpy(fichier_wav, audio, frequence)

        modele = _charger_modele_whisper()
        segments, _ = modele.transcribe(fichier_wav, language="fr", task="transcribe")

        texte = " ".join(segment.text.strip() for segment in segments if segment.text and segment.text.strip())
        texte = texte.strip()

        if not texte:
            raise RuntimeError("Le microphone a capté du son, mais la transcription est vide.")

        # Vérifier si le texte transcrit est une hallucination connue de Whisper
        # (surtout si le RMS indiquait un signal très faible)
        if rms < 0.05:  # RMS bas = risque d'hallucination
            if _texte_est_hallucination(texte):
                raise RuntimeError(
                    "Aucune parole détectée (hallucination Whisper sur silence détectée). "
                    "Veuillez réessayer et parler plus fort ou plus près du microphone."
                )

        return texte

    except RuntimeError:
        raise
    except Exception as erreur:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            "Erreur pendant l'enregistrement ou la transcription vocale. Vérifiez le microphone et les dépendances."
        ) from erreur
    finally:
        if fichier_wav and os.path.exists(fichier_wav):
            try:
                os.remove(fichier_wav)
            except OSError:
                pass


def ecouter_en_continu(
    callback_texte,
    evenement_arret,
    seuil_rms=0.012,
    silence_max_secondes=1.2,
    duree_min_parole_secondes=0.4,
) -> None:
    """Écoute le micro en continu et transmet chaque phrase reconnue.

    L'écoute s'arrête dès que ``evenement_arret`` est déclenché. La détection
    repose uniquement sur le niveau RMS de petits blocs audio.
    
    Peut être mise en pause via pause_ecoute_continue() pour éviter la latence
    causée par la compétition audio avec la synthèse vocale.
    """
    global _EVENEMENT_PAUSE_ECOUTE
    
    if seuil_rms < 0 or silence_max_secondes <= 0 or duree_min_parole_secondes <= 0:
        raise ValueError("Les paramètres de détection audio doivent être positifs.")

    # Initialiser l'événement de pause s'il n'existe pas encore
    if _EVENEMENT_PAUSE_ECOUTE is None:
        import threading
        _EVENEMENT_PAUSE_ECOUTE = threading.Event()
        print("[DEBUG] ecouter_en_continu() : création d'un nouvel événement _EVENEMENT_PAUSE_ECOUTE")
    
    # S'assurer que l'événement de pause est en état "non-pausé" au démarrage
    # (même s'il était en état "set" d'un appel antérieur).
    # Cela évite que la boucle d'écoute reste bloquée indéfiniment au démarrage.
    _EVENEMENT_PAUSE_ECOUTE.clear()
    print(f"[DEBUG] ecouter_en_continu() démarrage : _EVENEMENT_PAUSE_ECOUTE.is_set() = {_EVENEMENT_PAUSE_ECOUTE.is_set()}")

    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as erreur:
        raise RuntimeError(
            "L'écoute continue n'est pas disponible : la librairie 'sounddevice' ou 'numpy' manque."
        ) from erreur

    frequence = 16000
    duree_bloc = 0.1
    taille_bloc = int(frequence * duree_bloc)
    blocs_par_silence = max(1, int(silence_max_secondes / duree_bloc))
    blocs_min_parole = max(1, int(duree_min_parole_secondes / duree_bloc))
    blocs_parole = []
    blocs_silencieux = 0
    blocs_sonores = 0

    try:
        # Le flux est fermé automatiquement, même si la fenêtre est fermée.
        with sd.InputStream(
            samplerate=frequence,
            channels=1,
            dtype="float32",
            blocksize=taille_bloc,
        ) as flux:
            print("[DEBUG] ecouter_en_continu() : flux audio ouvert, début de la boucle d'écoute")
            iteration_count = 0
            while not evenement_arret.is_set():
                iteration_count += 1
                # Vérifier si l'écoute doit être mise en pause (ex: R.U.S.P.I parle).
                # On n'interrompt pas immédiatement la lecture en cours, on laisse
                # le flux en attente sans traiter les nouveaux blocs audio.
                if _EVENEMENT_PAUSE_ECOUTE.is_set():
                    print(f"[DEBUG] ecouter_en_continu() itération {iteration_count} : écoute en pause, attente...")
                while _EVENEMENT_PAUSE_ECOUTE.is_set() and not evenement_arret.is_set():
                    time.sleep(0.05)  # Attendre 50ms avant de revérifier
                
                bloc, _ = flux.read(taille_bloc)
                bloc = np.asarray(bloc, dtype=np.float32)
                if bloc.size == 0:
                    continue

                rms = float(np.sqrt(np.mean(bloc ** 2)))
                if iteration_count % 50 == 0:  # Log tous les 50 blocs (~5 secondes)
                    print(f"[DEBUG] ecouter_en_continu() itération {iteration_count} : RMS={rms:.4f}, seuil={seuil_rms}, blocs_sonores={blocs_sonores}, blocs_parole={len(blocs_parole)}")
                if rms >= seuil_rms:
                    blocs_parole.append(bloc.copy())
                    blocs_silencieux = 0
                    blocs_sonores += 1
                    continue

                if not blocs_parole:
                    continue

                blocs_silencieux += 1
                if blocs_silencieux < blocs_par_silence:
                    blocs_parole.append(bloc.copy())
                    continue

                if blocs_sonores >= blocs_min_parole:
                    print(f"[DEBUG] ecouter_en_continu() : détection de parole (blocs_sonores={blocs_sonores}), transcription en cours...")
                    audio = np.concatenate(blocs_parole, axis=0)
                    fichier_wav = None
                    try:
                        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fichier_temp:
                            fichier_wav = fichier_temp.name
                        _ecrire_wav_depuis_numpy(fichier_wav, audio, frequence)

                        modele = _charger_modele_whisper()
                        segments, _ = modele.transcribe(
                            fichier_wav, language="fr", task="transcribe"
                        )
                        texte = " ".join(
                            segment.text.strip()
                            for segment in segments
                            if segment.text and segment.text.strip()
                        ).strip()

                        # Les hallucinations sont ignorées comme dans ecouter_micro.
                        if texte and not _texte_est_hallucination(texte):
                            print(f"[DEBUG] ecouter_en_continu() : transcription réussie, texte='{texte}', appel du callback")
                            callback_texte(texte)
                        elif texte:
                            print(f"[DEBUG] ecouter_en_continu() : texte ignoré (hallucination Whisper) : '{texte}'")
                        else:
                            print(f"[DEBUG] ecouter_en_continu() : texte vide après transcription")
                    except Exception as erreur:
                        # Un segment bruité ne doit pas arrêter l'écoute suivante.
                        print(f"[DEBUG] ecouter_en_continu() : erreur lors de la transcription : {erreur}")
                    finally:
                        if fichier_wav and os.path.exists(fichier_wav):
                            try:
                                os.remove(fichier_wav)
                            except OSError:
                                pass

                blocs_parole = []
                blocs_silencieux = 0
                blocs_sonores = 0
    except Exception as erreur:
        if not evenement_arret.is_set():
            raise RuntimeError(
                "Erreur pendant l'écoute continue. Vérifiez le microphone et les dépendances."
            ) from erreur


def _nettoyer_texte_pour_parole(texte: str) -> str:
    """Nettoie le texte avant sa lecture vocale pour supprimer les marqueurs Markdown.

    Edge TTS lit certains caractères comme des symboles explicites (astérisque,
    tirets de liste, crochets de liens, guillemets) au lieu d'une phrase fluide.
    On les enlève avant génération audio pour obtenir une lecture naturelle.
    """
    if texte is None:
        return ""

    texte = str(texte).replace("\r\n", "\n").replace("\r", "\n")

    # Suppression des éléments Markdown courants et des liens.
    texte = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", texte)
    texte = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", texte)
    texte = texte.replace("**", "").replace("__", "").replace("*", "").replace("#", "")
    texte = texte.replace("`", "").replace("~", "")
    texte = texte.replace("_", "")

    # Nettoyage des listes, blocquotes et caractères typographiques qui sont lus
    # littéralement par synthèse vocale.
    texte = re.sub(r"^\s*[-*+]\s+", "", texte, flags=re.MULTILINE)
    texte = re.sub(r"^\s*\d+\.\s+", "", texte, flags=re.MULTILINE)
    texte = re.sub(r"^\s*>\s*", "", texte, flags=re.MULTILINE)
    texte = texte.replace(""", '"').replace(""", '"')
    texte = texte.replace("«", "").replace("»", "")
    texte = texte.replace("'", "'").replace("'", "'")
    texte = texte.replace("—", " ").replace("–", " ").replace("…", " ... ")
    texte = texte.replace("•", " ")

    texte = re.sub(r"\s+", " ", texte).strip()
    return texte


def parler(texte: str) -> None:
    """Lit à voix haute le texte reçu en français via Edge TTS.
    
    Pause l'écoute continue (si elle est active) pour éviter la compétition audio
    pendant la synthèse et la lecture vocale, puis la reprend après.
    """
    texte = _nettoyer_texte_pour_parole(texte)
    if not texte:
        return

    # Mettre en pause l'écoute continue si le mode mains libres est actif
    pause_ecoute_continue()

    try:
        import edge_tts
    except ImportError:
        print(
            "Synthèse vocale indisponible : la librairie 'edge-tts' manque. "
            "Installez les dépendances pour activer la lecture vocale."
        )
        reprendre_ecoute_continue()
        return

    fichier_temp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fichier_temporaire:
            fichier_temp = Path(fichier_temporaire.name)

        async def _generer_audio() -> None:
            voix = "fr-FR-HenriNeural"
            # On ajoute un très court silence au début (points de suspension)
            # pour éviter que le tout premier mot ne soit coupé par le lecteur
            # audio qui met une fraction de seconde à s'initialiser.
            texte_avec_marge = "... " + texte
            lecteur = edge_tts.Communicate(texte_avec_marge, voix)
            await lecteur.save(str(fichier_temp))

        asyncio.run(_generer_audio())

        if not fichier_temp.exists() or fichier_temp.stat().st_size == 0:
            raise RuntimeError("Le fichier audio généré est vide.")

        _jouer_mp3_windows(str(fichier_temp))

    except Exception as erreur:
        print(f"Erreur de synthèse vocale : {erreur}")
    finally:
        if fichier_temp and fichier_temp.exists():
            try:
                fichier_temp.unlink(missing_ok=True)
            except OSError:
                pass
        
        # Reprendre l'écoute continue après la synthèse et la lecture
        reprendre_ecoute_continue()


def _jouer_mp3_windows(chemin_fichier: str) -> None:
    """Joue un fichier MP3 de façon synchrone via winmm.dll (intégré à Windows).

    On attend la fin de la lecture avant de continuer, pour pouvoir ensuite
    supprimer le fichier temporaire sans risque de coupure du son.

    Chaque lecture a un alias MCI unique pour éviter les collisions lorsque des
    arrêts ou des relances se produisent rapidement. Toutes les commandes MCI
    sont exécutées dans ce thread, y compris l'arrêt demandé par la GUI.
    """
    import ctypes

    global _WINMM_LECTURE, _LECTURE_EN_COURS, _ALIAS_LECTURE_ACTIF, _ALIAS_LECTURE

    winmm = ctypes.windll.winmm
    _configurer_mci_send_string(winmm)
    alias_lecture = f"{_ALIAS_LECTURE}_{threading.get_ident()}_{time.monotonic_ns()}"
    _EVENEMENT_ARRET_LECTURE.clear()

    with _VERROU_LECTURE:
        _ALIAS_LECTURE_ACTIF = alias_lecture
        commande_ouverture = f'open "{chemin_fichier}" type mpegvideo alias {alias_lecture}'
        code_ouverture = winmm.mciSendStringW(
            ctypes.c_wchar_p(commande_ouverture),
            None,
            0,
            None,
        )
        print(f"[DEBUG] _jouer_mp3_windows() : open alias='{alias_lecture}' code={code_ouverture}")
        _WINMM_LECTURE = winmm
        _LECTURE_EN_COURS = True

    try:
        # La lecture est non bloquante : le thread audio reste libre de traiter
        # la demande d'arrêt et de conserver le contexte MCI d'origine.
        commande_play = f"play {alias_lecture}"
        code_play = winmm.mciSendStringW(ctypes.c_wchar_p(commande_play), None, 0, None)
        print(f"[DEBUG] _jouer_mp3_windows() : play alias='{alias_lecture}' code={code_play}")

        if code_play == 0:
            while True:
                time.sleep(0.1)

                if _EVENEMENT_ARRET_LECTURE.is_set():
                    commande_stop = f"stop {alias_lecture}"
                    print(
                        f"[DEBUG] _jouer_mp3_windows() : arrêt détecté dans le thread audio -> '{commande_stop}'"
                    )
                    code_stop = winmm.mciSendStringW(
                        ctypes.c_wchar_p(commande_stop), None, 0, None
                    )
                    print(f"[DEBUG] _jouer_mp3_windows() : code retour stop = {code_stop}")
                    if code_stop != 0:
                        print(f"[DEBUG] _jouer_mp3_windows() : ERREUR MCI stop, code={code_stop}")
                    break

                # Le buffer reçoit le mode retourné par MCI (playing/stopped).
                mode_lecture = ctypes.create_unicode_buffer(32)
                commande_status = f"status {alias_lecture} mode"
                code_status = winmm.mciSendStringW(
                    ctypes.c_wchar_p(commande_status), mode_lecture, 32, None
                )
                mode = mode_lecture.value.strip().lower()
                print(
                    f"[DEBUG] _jouer_mp3_windows() : status alias='{alias_lecture}' "
                    f"mode='{mode}' code={code_status}"
                )
                if code_status != 0 or mode in ("stopped", "", "not ready"):
                    break
    finally:
        with _VERROU_LECTURE:
            commande_close = f"close {alias_lecture}"
            code_close = winmm.mciSendStringW(ctypes.c_wchar_p(commande_close), None, 0, None)
            print(f"[DEBUG] _jouer_mp3_windows() : close alias='{alias_lecture}' code={code_close}")
            _LECTURE_EN_COURS = False
            _WINMM_LECTURE = None
            if _ALIAS_LECTURE_ACTIF == alias_lecture:
                _ALIAS_LECTURE_ACTIF = None
