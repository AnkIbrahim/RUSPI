"""Gestion des rappels et alarmes pour R.U.S.P.I.

Ce module gère la création, le stockage et la vérification des rappels.
Le système est volontairement simple pour rester facile à comprendre :
- un fichier JSON contient la liste des rappels,
- une vérification périodique du module principal regarde s'il faut déclencher
  un rappel,
- chaque rappel est marqué comme "en_attente" puis "déclenché" une fois
  qu'il est arrivé à échéance.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

DOSSIER_DATA = Path(__file__).resolve().parent.parent / "data"
CHEMIN_FICHIER_RAPPELS = DOSSIER_DATA / "rappels.json"


def _assurer_dossier_data() -> None:
    """Crée le dossier data s'il n'existe pas."""
    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)


def _charger_rappels() -> list:
    """Lit la liste des rappels depuis le fichier JSON.

    Si le fichier n'existe pas ou est vide, on retourne une liste vide.
    """
    _assurer_dossier_data()

    if not CHEMIN_FICHIER_RAPPELS.exists():
        return []

    try:
        contenu = CHEMIN_FICHIER_RAPPELS.read_text(encoding="utf-8")
        if not contenu.strip():
            return []
        donnees = json.loads(contenu)
        return donnees if isinstance(donnees, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _sauvegarder_rappels(rappels: list) -> None:
    """Écrit la liste des rappels dans le fichier JSON."""
    _assurer_dossier_data()
    CHEMIN_FICHIER_RAPPELS.write_text(json.dumps(rappels, ensure_ascii=False, indent=2), encoding="utf-8")


def _valider_heure(heure: str) -> tuple[int, int]:
    """Valide un format HH:MM et retourne les heures/minutes.

    Raises:
        ValueError: si l'heure n'est pas au bon format.
    """
    if not isinstance(heure, str):
        raise ValueError("L'heure doit être une chaîne de caractères au format HH:MM.")

    heure = heure.strip()
    if len(heure) != 5 or heure[2] != ":":
        raise ValueError("Format d'heure invalide. Utilisez le format HH:MM, par exemple 09:30.")

    try:
        heures = int(heure[:2])
        minutes = int(heure[3:5])
    except ValueError as erreur:
        raise ValueError("Format d'heure invalide. Utilisez le format HH:MM, par exemple 09:30.") from erreur

    if not (0 <= heures <= 23 and 0 <= minutes <= 59):
        raise ValueError("Heure invalide. Les heures doivent être entre 00 et 23 et les minutes entre 00 et 59.")

    return heures, minutes


def ajouter_rappel(texte: str, heure: str) -> str:
    """Ajoute un rappel dans la liste et le sauvegarde localement.

    Args:
        texte: Texte du rappel à afficher.
        heure: Heure au format HH:MM dans le système 24h.

    Returns:
        Un message de confirmation lisible en français.
    """
    texte = (texte or "").strip()
    if not texte:
        raise ValueError("Le texte du rappel ne peut pas être vide.")

    heures, minutes = _valider_heure(heure)

    maintenant = datetime.now()
    date_rappel = datetime(
        maintenant.year,
        maintenant.month,
        maintenant.day,
        heures,
        minutes,
    )

    if date_rappel <= maintenant:
        date_rappel = date_rappel + timedelta(days=1)

    rappel = {
        "texte": texte,
        "heure": f"{heures:02d}:{minutes:02d}",
        "date_rappel": date_rappel.strftime("%Y-%m-%dT%H:%M:%S"),
        "statut": "en_attente",
    }

    rappels = _charger_rappels()
    rappels.append(rappel)
    _sauvegarder_rappels(rappels)

    return (
        f"Rappel ajouté avec succès : '{texte}' pour {rappel['heure']} "
        f"le {date_rappel.strftime('%d/%m/%Y')} ."
    )


def lister_rappels() -> str:
    """Retourne la liste des rappels en attente sous forme lisible."""
    rappels = _charger_rappels()
    en_attente = [r for r in rappels if r.get("statut") == "en_attente"]

    if not en_attente:
        return "Vous n'avez aucun rappel en attente."

    lignes = ["Voici vos rappels en attente :"]
    for index, rappel in enumerate(en_attente, start=1):
        texte = rappel.get("texte", "Rappel sans texte")
        heure = rappel.get("heure", "heure inconnue")
        date_rappel = rappel.get("date_rappel", "")
        if date_rappel:
            try:
                date_objet = datetime.strptime(date_rappel, "%Y-%m-%dT%H:%M:%S")
                date_formatee = date_objet.strftime("%d/%m/%Y à %H:%M")
            except ValueError:
                date_formatee = date_rappel
        else:
            date_formatee = "date inconnue"
        lignes.append(f"{index}. {texte} — {heure} ({date_formatee})")

    return "\n".join(lignes)


def verifier_rappels_en_attente() -> list:
    """Vérifie les rappels expirés et retourne les textes à annoncer.

    Cette fonction compare l'heure actuelle avec la date prévue du rappel.
    Si le rappel est arrivé et qu'il est encore en attente, on le marque comme
    "déclenché" puis on le renvoie pour que le thread principal l'annonce.
    """
    rappels = _charger_rappels()
    maintenant = datetime.now()
    textes_a_annoncer: list[str] = []

    for rappel in rappels:
        statut = rappel.get("statut")
        date_rappel = rappel.get("date_rappel")
        if statut != "en_attente" or not date_rappel:
            continue

        try:
            date_objet = datetime.strptime(date_rappel, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue

        if maintenant >= date_objet:
            texte = rappel.get("texte", "Rappel")
            rappel["statut"] = "déclenché"
            textes_a_annoncer.append(texte)

    _sauvegarder_rappels(rappels)
    return textes_a_annoncer
