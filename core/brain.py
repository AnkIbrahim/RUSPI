"""Logique de communication avec l'API Google Gemini.

Ce module centralise l'appel au modèle Gemini et prépare le contexte de
conversation pour une meilleure interaction avec l'assistant.
"""

import os
from typing import List, Dict, Any

from google import genai
from google.genai import types
from google.genai.errors import ServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from core.tools import (
    creer_rappel,
    obtenir_date_heure,
    obtenir_meteo,
    ouvrir_application,
    rechercher_sur_le_web,
    voir_mes_rappels,
)


def demander_a_ruspi(message: str, historique: List[Dict[str, str]] | None = None) -> str:
    """Envoie un message au modèle Gemini en gardant le contexte.

    Args:
        message: Message de l'utilisateur.
        historique: Historique complet de la conversation.

    Returns:
        La réponse du modèle Gemini sous forme de chaîne.

    Raises:
        ValueError: Si la clé API n'est pas présente.
        RuntimeError: Si l'appel API échoue après plusieurs tentatives.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("Clé API GEMINI_API_KEY manquante. Ajoutez-la dans votre fichier .env.")

    client = genai.Client(api_key=api_key)

    messages = historique or []

    contents = []
    for item in messages:
        role = item.get("role", "user")
        contenu = item.get("content", "")
        if role == "user":
            contents.append({"role": "user", "parts": [{"text": contenu}]})
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": contenu}]})

    contents.append({"role": "user", "parts": [{"text": message}]})

    instruction_systeme = (
        "Tu es R.U.S.P.I (Rien qu'Un Système Particulièrement Intelligent), "
        "un assistant IA personnel inspiré de J.A.R.V.I.S. "
        "Tu es serviable, précis et tu réponds toujours en français. "
        "Tu peux désormais effectuer des actions : donner l'heure, ouvrir des "
        "applications Windows, lancer des recherches web, donner la météo "
        "actuelle d'une ville, créer un rappel et lister les rappels en attente. "
        "Quand c'est pertinent, utilise ces outils plutôt que de répondre "
        "uniquement en texte. Ne te présente jamais comme Gemini — tu es R.U.S.P.I."
    )

    try:
        reponse = _appel_gemini_avec_retry(client, contents, instruction_systeme)

        if hasattr(reponse, "text") and reponse.text:
            return reponse.text

        if hasattr(reponse, "candidates") and reponse.candidates:
            first = reponse.candidates[0]
            if hasattr(first, "content") and hasattr(first.content, "parts"):
                texte = "".join(part.text for part in first.content.parts if hasattr(part, "text"))
                if texte:
                    return texte

        return "Je n'ai pas pu générer de réponse exploitable pour le moment."

    except Exception as erreur:
        raise RuntimeError(f"Erreur lors de l'appel Gemini : {erreur}") from erreur


@retry(
    # On réessaie uniquement si l'erreur vient d'un problème serveur (503, 500, etc.)
    retry=retry_if_exception_type(ServerError),
    # Jusqu'à 3 tentatives au total.
    stop=stop_after_attempt(3),
    # Attente progressive entre les tentatives : 2s, puis 4s, puis 8s.
    wait=wait_exponential(multiplier=2, min=2, max=10),
    reraise=True,
)
def _appel_gemini_avec_retry(client: genai.Client, contents: list, instruction_systeme: str):
    """Appelle l'API Gemini avec plusieurs tentatives automatiques en cas de surcharge serveur."""
    return client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=contents,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=800,
            system_instruction=instruction_systeme,
            tools=[
                obtenir_date_heure,
                ouvrir_application,
                rechercher_sur_le_web,
                obtenir_meteo,
                creer_rappel,
                voir_mes_rappels,
            ],
        ),
    )