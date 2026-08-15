"""Outils d'action disponibles pour R.U.S.P.I.

Ces fonctions permettent au modèle Gemini d'effectuer des actions utiles sur
l'ordinateur local, comme donner l'heure, lancer une application ou ouvrir une
recherche web. Chaque fonction a une docstring claire pour aider le modèle à
choisir le bon outil au bon moment.
"""

import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from urllib.parse import quote


# Cache local en mémoire des actions déjà exécutées récemment.
# Ce mécanisme évite qu'un retry Gemini relance plusieurs fois la même action
# pour une seule demande utilisateur.
_ACTIONS_REALISEES = {}
_ACTIONS_LOCK = threading.Lock()
_ACTIONS_TTL = 5.0


def _a_ete_deja_execute_recentement(nom_action: str, *arguments) -> bool:
    """Vérifie si une action identique a déjà été exécutée il y a moins de 5 secondes.

    Cette protection est volontairement simple et robuste pour un projet de
    débutant. Elle ne bloque pas les vraies erreurs serveur avant exécution,
    car elle ne s'applique qu'au moment où un outil est réellement appelé.
    """
    cle = (nom_action, arguments)
    maintenant = time.monotonic()

    with _ACTIONS_LOCK:
        dernier = _ACTIONS_REALISEES.get(cle)
        if dernier is not None and maintenant - dernier < _ACTIONS_TTL:
            return True

        _ACTIONS_REALISEES[cle] = maintenant
        return False


def obtenir_date_heure() -> str:
    """Retourne la date et l'heure actuelles du système en français.

    Cette fonction sert à donner l'heure exacte à l'utilisateur ou à contextualiser
    une réponse en fonction du moment de la journée.

    Returns:
        Une chaîne lisible, par exemple : "vendredi 15 août 2026, 14h32".
    """
    maintenant = datetime.now()
    return maintenant.strftime("%A %d %B %Y, %Hh%M").capitalize()


def ouvrir_application(nom_application: str) -> str:
    """Ouvre une application Windows à partir d'un nom simple.

    Args:
        nom_application: Nom de l'application à ouvrir. Les valeurs reconnues sont :
            "calculatrice", "bloc-notes", "navigateur" et "explorateur".

    Returns:
        Un message de confirmation ou une explication si le nom est invalide.
    """
    nom = nom_application.strip().lower()

    if _a_ete_deja_execute_recentement("ouvrir_application", nom):
        return "Action déjà effectuée récemment pour cette application."

    if nom == "calculatrice":
        subprocess.Popen(["calc"])
        return "J'ai ouvert la calculatrice."

    if nom == "bloc-notes":
        subprocess.Popen(["notepad"])
        return "J'ai ouvert le bloc-notes."

    if nom == "navigateur":
        # On ouvre le navigateur par défaut sur la page d'accueil.
        subprocess.Popen(["cmd", "/c", "start", "", "https://www.google.com"])
        return "J'ai ouvert le navigateur web."

    if nom == "explorateur":
        subprocess.Popen(["explorer"])
        return "J'ai ouvert l'explorateur de fichiers."

    return (
        "Je ne reconnais pas cette application. "
        "Les noms acceptés sont : calculatrice, bloc-notes, navigateur, explorateur."
    )


def rechercher_sur_le_web(requete: str) -> str:
    """Ouvre une recherche Google pour la requête donnée.

    Args:
        requete: Terme ou question à rechercher sur le web.

    Returns:
        Un message indiquant que la recherche a bien été lancée.
    """
    requete_normalisee = requete.strip()

    if _a_ete_deja_execute_recentement("rechercher_sur_le_web", requete_normalisee):
        return "Action déjà effectuée récemment pour cette recherche."

    requete_encodee = quote(requete_normalisee)
    url = "https://www.google.com/search?q=" + requete_encodee
    webbrowser.open(url)
    return f"J'ai lancé une recherche Google pour : {requete_normalisee}."
