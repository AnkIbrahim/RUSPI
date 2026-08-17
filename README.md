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

### Mode Terminal (par défaut)

```bash
python main.py
```

Cela lance R.U.S.P.I en mode conversationnel dans le terminal.

### Mode Interface Graphique (GUI)

```bash
python gui.py
```

Cela lance R.U.S.P.I avec une interface graphique Tkinter moderne.

## Utilisation

### Mode Terminal

- Écrivez votre message dans le terminal.
- Tapez `quitter` ou `exit` pour fermer l'application.
- L'historique de conversation est conservé en mémoire pendant la session.

### Mode Interface Graphique (GUI)

La GUI Tkinter offre une expérience améliorée :

1. **Sélection de session** : Au démarrage, choisissez de charger une session existante ou d'en créer une nouvelle.

2. **Zone de conversation** :
   - Affiche l'historique avec codes couleurs : **Vous** en bleu, **R.U.S.P.I** en vert
   - Les rappels s'affichent en orange
   - Défilement automatique

3. **Envoi de messages** :
   - Tapez dans le champ de saisie et appuyez sur **Entrée** ou cliquez **Envoyer**
   - R.U.S.P.I répond automatiquement
   - La réponse est lue à voix haute (synthèse vocale Edge-TTS)

4. **Enregistrement vocal** :
   - Cliquez sur le bouton **🎤 Parler**
   - Parlez pendant 6 secondes maximum
   - Le texte est transcrit automatiquement et envoyé à R.U.S.P.I
   - La réponse s'affiche et se fait entendre

5. **Rappels en arrière-plan** :
   - Les rappels programmés s'affichent automatiquement dans la fenêtre
   - Une notification système est aussi lancée
   - Le rappel est lu à voix haute

**Architecture thread-safe** :
- Les appels longs (API Gemini, microphone) tournent en arrière-plan
- L'interface Tkinter reste réactive pendant ce temps
- Communication via queue thread-safe

## Notes

- Le fichier `.env` contient votre clé API sensible et ne doit jamais être partagé.
- Le projet est volontairement simple et prêt à être étendu avec de nouveaux outils ou fonctionnalités.
