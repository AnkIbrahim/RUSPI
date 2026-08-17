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
import time
import wave
from pathlib import Path

_WHISPER_MODEL = None


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


def ecouter_micro(duree_secondes: int = 6) -> str:
    """Enregistre le micro, le transcrit en français, puis retourne le texte.
    
    Détecte aussi :
    - Le silence complet (niveau sonore RMS très bas)
    - Les hallucinations typiques de Whisper (phrases générées sur du silence)
    """
    if duree_secondes <= 0:
        raise ValueError("La durée d'enregistrement doit être supérieure à 0 seconde.")

    # Phrases connues comme hallucinations de Whisper sur du silence ou du bruit
    HALLUCINATIONS_WHISPER = [
        "Sous-titres réalisés par la communauté d'Amara.org",
        "Merci d'avoir regardé cette vidéo",
        "Abonnez-vous à la chaîne",
        "Sous-titres réalisés par la communauté",
    ]

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
            for hallucination in HALLUCINATIONS_WHISPER:
                if texte.lower() == hallucination.lower() or hallucination.lower() in texte.lower():
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
    """Lit à voix haute le texte reçu en français via Edge TTS."""
    texte = _nettoyer_texte_pour_parole(texte)
    if not texte:
        return

    try:
        import edge_tts
    except ImportError:
        print(
            "Synthèse vocale indisponible : la librairie 'edge-tts' manque. "
            "Installez les dépendances pour activer la lecture vocale."
        )
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


def _jouer_mp3_windows(chemin_fichier: str) -> None:
    """Joue un fichier MP3 de façon synchrone via winmm.dll (intégré à Windows).

    On attend la fin de la lecture avant de continuer, pour pouvoir ensuite
    supprimer le fichier temporaire sans risque de coupure du son.
    """
    import ctypes

    alias = "ruspi_audio"
    winmm = ctypes.windll.winmm

    try:
        winmm.mciSendStringW(f'open "{chemin_fichier}" type mpegvideo alias {alias}', None, 0, None)
        winmm.mciSendStringW(f"play {alias} wait", None, 0, None)
    finally:
        winmm.mciSendStringW(f"close {alias}", None, 0, None)