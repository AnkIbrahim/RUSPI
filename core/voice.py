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
        # Le modèle 'base' est un bon compromis entre performance et charge mémoire.
        _WHISPER_MODEL = WhisperModel("base", device="cpu", compute_type="int8")
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
    """Enregistre le micro, le transcrit en français, puis retourne le texte."""
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

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as fichier_temp:
            fichier_wav = fichier_temp.name

        _ecrire_wav_depuis_numpy(fichier_wav, audio, frequence)

        modele = _charger_modele_whisper()
        segments, _ = modele.transcribe(fichier_wav, language="fr", task="transcribe")

        texte = " ".join(segment.text.strip() for segment in segments if segment.text and segment.text.strip())
        texte = texte.strip()

        if not texte:
            raise RuntimeError("Le microphone a capté du son, mais la transcription est vide.")

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


def parler(texte: str) -> None:
    """Lit à voix haute le texte reçu en français via Edge TTS."""
    texte = (texte or "").strip()
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
            voix = "fr-FR-DeniseNeural"
            lecteur = edge_tts.Communicate(texte, voix)
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