"""Point d'entrée principal pour l'assistant R.U.S.P.I.

Ce fichier lance une boucle d'interaction en terminal, envoie les messages
à l'API Gemini et garde l'historique de conversation dans des fichiers JSON.
"""

from pathlib import Path

from dotenv import load_dotenv

from core.brain import demander_a_ruspi
from core.memory import (
    ConversationMemory,
    DOSSIER_SESSIONS,
    charger_session,
    lister_sessions,
    nouveau_fichier_session,
    sauvegarder_session,
)
from core.voice import ecouter_micro, parler


def choisir_session() -> tuple[str | None, str | None]:
    """Propose à l'utilisateur de démarrer une nouvelle session ou d'en reprendre une."""
    sessions = lister_sessions()[:5]

    if not sessions:
        print("Aucune session enregistrée. Une nouvelle conversation va être créée.")
        return None, None

    print("\nSessions disponibles (5 plus récentes) :")
    for index, nom_fichier in enumerate(sessions, start=1):
        print(f"  {index}. {nom_fichier}")
    print("  0. Démarrer une nouvelle conversation")

    while True:
        choix = input("Choisissez une session (ou 0 pour en créer une nouvelle) > ").strip()

        if choix in {"", "0"}:
            return None, None

        try:
            numero = int(choix)
        except ValueError:
            print("Choix invalide. Entrez un numéro ou 0.")
            continue

        if 1 <= numero <= len(sessions):
            return sessions[numero - 1], str(DOSSIER_SESSIONS / sessions[numero - 1])

        print(f"Choix invalide. Entrez un nombre entre 1 et {len(sessions)}.")


def main() -> None:
    """Lance l'application en boucle interactive."""
    # On charge les variables depuis le fichier .env si il existe.
    load_dotenv()

    print("R.U.S.P.I est prêt.")
    print("Tapez 'quitter' ou 'exit' pour fermer le programme.")

    nom_session, chemin_session = choisir_session()

    if nom_session and chemin_session:
        historique = charger_session(nom_session)
        memoire = ConversationMemory(chemin_session)
        memoire.historique = historique
        print(f"Session chargée : {nom_session}")
    else:
        chemin_nouveau = DOSSIER_SESSIONS / nouveau_fichier_session()
        memoire = ConversationMemory(str(chemin_nouveau))
        sauvegarder_session(chemin_nouveau, memoire.historique)
        print(f"Nouvelle session créée : {chemin_nouveau.name}")

    while True:
        # Le prompt est simple et conçu pour un usage en terminal.
        message = input("Vous > ").strip()

        if not message:
            print("Je n'ai pas entendu de message. Réessayez.")
            continue

        # Si l'utilisateur demande à quitter, on sort proprement de la boucle.
        if message.lower() in {"quitter", "exit"}:
            print("Au revoir. R.U.S.P.I se met en veille.")
            break

        # Commandes vocales : l'utilisateur peut demander la capture du micro
        # au lieu d'écrire un message texte.
        if message.lower() in {"vocal", "voix"}:
            print("Préparez-vous...")
            import time

            time.sleep(1)
            print("Parlez maintenant !")
            try:
                message = ecouter_micro(6)
                print(f"Vous (voix) > {message}")
            except RuntimeError as erreur:
                print(f"Erreur vocale : {erreur}")
                continue
            except ValueError as erreur:
                print(f"Erreur vocale : {erreur}")
                continue

        # Ajout du message utilisateur dans l'historique avant l'appel IA.
        memoire.ajouter_message("user", message)
        sauvegarder_session(memoire.fichier_sauvegarde, memoire.historique)

        try:
            reponse = demander_a_ruspi(message, historique=memoire.historique)
        except ValueError as erreur:
            print(f"Erreur : {erreur}")
            print("Créez un fichier .env à partir de .env.example et ajoutez votre clé GEMINI_API_KEY.")
            break
        except RuntimeError as erreur:
            print(f"Erreur de communication avec Gemini : {erreur}")
            continue

        # On garde aussi la réponse de l'IA dans l'historique.
        memoire.ajouter_message("assistant", reponse)
        sauvegarder_session(memoire.fichier_sauvegarde, memoire.historique)
        print(f"R.U.S.P.I > {reponse}")
        parler(reponse)


if __name__ == "__main__":
    main()
