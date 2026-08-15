"""Gestion de la mémoire de session de R.U.S.P.I.

Les conversations sont enregistrées dans des fichiers JSON dans le dossier
`data/sessions/` afin de pouvoir les reprendre plus tard.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List


DOSSIER_SESSIONS = Path(__file__).resolve().parent.parent / "data" / "sessions"


def _assurer_dossier_sessions() -> Path:
    """Crée le dossier de sauvegarde si besoin."""
    DOSSIER_SESSIONS.mkdir(parents=True, exist_ok=True)
    return DOSSIER_SESSIONS


def nouveau_fichier_session() -> str:
    """Crée un nom de fichier unique pour une nouvelle session.

    Exemple : session_2026-08-15_10-30-00.json
    """
    _assurer_dossier_sessions()
    horodatage = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"session_{horodatage}.json"


def sauvegarder_session(chemin_fichier: str | Path, historique: List[Dict[str, str]]) -> str:
    """Écrit un historique complet dans un fichier JSON."""
    chemin = Path(chemin_fichier)
    chemin.parent.mkdir(parents=True, exist_ok=True)

    with open(chemin, "w", encoding="utf-8") as fichier:
        json.dump(historique, fichier, ensure_ascii=False, indent=2)
        fichier.write("\n")

    return str(chemin)


def lister_sessions() -> List[str]:
    """Retourne les noms des sessions enregistrées, du plus récent au plus ancien."""
    dossier = _assurer_dossier_sessions()
    fichiers = [fichier.name for fichier in dossier.glob("session_*.json") if fichier.is_file()]
    return sorted(fichiers, reverse=True)


def charger_session(nom_fichier: str) -> List[Dict[str, str]]:
    """Charge l'historique d'une session à partir du nom du fichier."""
    dossier = _assurer_dossier_sessions()
    chemin = Path(nom_fichier)

    if not chemin.is_absolute():
        chemin = dossier / nom_fichier

    with open(chemin, "r", encoding="utf-8") as fichier:
        historique = json.load(fichier)

    if not isinstance(historique, list):
        raise ValueError(f"Le fichier de session {chemin} ne contient pas une liste valide.")

    return historique


class ConversationMemory:
    """Stocke les messages de discussion pour la session actuelle."""

    def __init__(self, fichier_sauvegarde: str | None = None):
        self.historique: List[Dict[str, str]] = []
        self.fichier_sauvegarde = fichier_sauvegarde

    def ajouter_message(self, role: str, content: str) -> None:
        """Ajoute un message dans l'historique."""
        self.historique.append({"role": role, "content": content})

    def sauvegarder_json(self, chemin: str | None = None) -> None:
        """Sauvegarde l'historique dans un fichier JSON."""
        cible = chemin or self.fichier_sauvegarde
        if not cible:
            raise ValueError("Aucun chemin de sauvegarde n'a été fourni.")

        sauvegarder_session(cible, self.historique)

    def charger_json(self, chemin: str) -> None:
        """Charge un historique depuis un fichier JSON."""
        self.historique = charger_session(chemin)
