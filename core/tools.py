"""Outils d'action disponibles pour R.U.S.P.I.

Ces fonctions permettent au modèle Gemini d'effectuer des actions utiles sur
l'ordinateur local, comme donner l'heure, lancer une application, ouvrir une
recherche web ou consulter la météo d'une ville. Chaque fonction a une
docstring claire pour aider le modèle à choisir le bon outil au bon moment.
"""

import subprocess
import threading
import time
import webbrowser
from datetime import datetime
from urllib.parse import quote

import requests

from core.rappels import ajouter_rappel, lister_rappels


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


def _traduire_code_meteo(weathercode: int | None) -> str:
    """Convertit le code météo WMO en une description lisible en français.

    Open-Meteo renvoie un code WMO standard. On traduit ici les valeurs les plus
    courantes pour une réponse simple et compréhensible par un débutant.
    """
    if weathercode is None:
        return "conditions météo inconnues"

    if weathercode == 0:
        return "ciel dégagé"
    if weathercode in (1, 2, 3):
        return "ciel partiellement nuageux"
    if weathercode in (45, 48):
        return "brouillard"
    if 51 <= weathercode <= 67:
        return "pluie"
    if 71 <= weathercode <= 77:
        return "neige"
    if 80 <= weathercode <= 99:
        return "averses orageuses"
    if weathercode in (90, 95, 96, 99):
        return "orage"
    return "conditions météo variables"


def obtenir_meteo(ville: str) -> str:
    """Retourne la météo actuelle d'une ville via l'API Open-Meteo.

    Étapes :
    1. On cherche la ville pour récupérer ses coordonnées GPS.
    2. On demande la météo actuelle à partir de ces coordonnées.
    3. On reformate la réponse dans une phrase claire en français.

    Args:
        ville: Nom de la ville à interroger.

    Returns:
        Une phrase lisible en français, même en cas d'erreur.
    """
    ville = ville.strip()
    if not ville:
        return "Je n'ai pas reçu le nom d'une ville."

    if _a_ete_deja_execute_recentement("obtenir_meteo", ville):
        return "J'ai déjà vérifié la météo de cette ville récemment."

    # Première requête : géocodage de la ville pour obtenir latitude/longitude.
    try:
        reponse_geocodage = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": ville, "count": 1, "language": "fr"},
            timeout=5,
        )
    except requests.exceptions.Timeout:
        return "La recherche météo a pris trop de temps. Réessayez dans quelques secondes."
    except requests.exceptions.RequestException:
        return "L'API de géolocalisation météo est actuellement indisponible."

    if reponse_geocodage.status_code != 200:
        return "L'API météo n'a pas pu trouver cette ville pour le moment."

    donnees_geocodage = reponse_geocodage.json()
    resultats = donnees_geocodage.get("results") or []
    if not resultats:
        return f"Je n'ai pas trouvé de ville nommée '{ville}'."

    lieu = resultats[0]
    latitude = lieu.get("latitude")
    longitude = lieu.get("longitude")
    nom_lieu = lieu.get("name", ville)

    if latitude is None or longitude is None:
        return f"Je n'ai pas pu récupérer les coordonnées de '{ville}'."

    # Deuxième requête : météo actuelle avec les coordonnées GPS.
    try:
        reponse_meteo = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": "true",
                "timezone": "auto",
            },
            timeout=5,
        )
    except requests.exceptions.Timeout:
        return "La récupération de la météo actuelle a pris trop de temps."
    except requests.exceptions.RequestException:
        return "L'API météo est actuellement indisponible."

    if reponse_meteo.status_code != 200:
        return "L'API météo ne répond pas correctement pour le moment."

    donnees_meteo = reponse_meteo.json()
    weather = donnees_meteo.get("current_weather") or {}
    temperature = weather.get("temperature")
    windspeed = weather.get("windspeed")
    weathercode = weather.get("weathercode")

    if temperature is None:
        return f"Je n'ai pas de donnée météo actuelle pour {nom_lieu}."

    description = _traduire_code_meteo(weathercode)
    temperature_arrondie = int(round(float(temperature)))
    vent_arrondi = int(round(float(windspeed))) if windspeed is not None else None

    if vent_arrondi is not None:
        article = "un" if description.startswith("c") else "de"
        if description.startswith("b"):
            article = "un"
        return (
            f"À {nom_lieu}, il fait actuellement {temperature_arrondie}°C "
            f"avec {article} {description} et un vent de {vent_arrondi} km/h."
        )

    article = "un" if description.startswith("c") else "de"
    if description.startswith("b"):
        article = "un"
    return f"À {nom_lieu}, il fait actuellement {temperature_arrondie}°C avec {article} {description}."


def creer_rappel(texte: str, heure: str) -> str:
    """Crée un rappel planifié à une heure précise en français.

    Args:
        texte: Texte du rappel à afficher.
        heure: Heure au format HH:MM sur 24h.

    Returns:
        Une confirmation de création du rappel.
    """
    try:
        return ajouter_rappel(texte, heure)
    except ValueError as erreur:
        return str(erreur)


def voir_mes_rappels() -> str:
    """Retourne la liste des rappels en attente au format lisible."""
    return lister_rappels()
