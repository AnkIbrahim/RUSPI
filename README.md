# R.U.S.P.I

R.U.S.P.I (Rien qu'Un Système Particulièrement Intelligent) est un assistant personnel inspiré de J.A.R.V.I.S, conçu pour discuter avec vous depuis le terminal et utiliser l'API Google Gemini.

## Prérequis

- Python 3.10 ou plus
- Un accès à l'API Gemini avec une clé valide

## Installation

1. Ouvrez un terminal dans le dossier du projet.
2. Créez un environnement virtuel si vous le souhaitez :
   ```bash
   python -m venv venv
   ```
3. Activez l'environnement :
   - Windows :
     ```bash
     venv\Scripts\activate
     ```
   - Linux / macOS :
     ```bash
     source venv/bin/activate
     ```
4. Installez les dépendances :
   ```bash
   pip install -r requirements.txt
   ```
5. Créez votre fichier `.env` à partir du modèle `.env.example` :
   ```bash
   copy .env.example .env
   ```
   puis ajoutez votre clé API Gemini dans le fichier `.env`.

## Lancement

```bash
python main.py
```

## Utilisation

- Écrivez votre message dans le terminal.
- Tapez `quitter` ou `exit` pour fermer l'application.
- L'historique de conversation est conservé en mémoire pendant la session.

## Notes

- Le fichier `.env` contient votre clé API sensible et ne doit jamais être partagé.
- Le projet est volontairement simple et prêt à être étendu avec de nouveaux outils ou fonctionnalités.
