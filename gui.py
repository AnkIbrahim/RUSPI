"""Interface graphique Tkinter pour l'assistant R.U.S.P.I.

Cette interface fournit une fenêtre desktop simple permettant de converser
avec R.U.S.P.I en texte ou en vocal, avec sauvegarde automatique de la session.

La fenêtre affiche :
- Une zone de conversation avec des styles différents pour l'utilisateur et R.U.S.P.I
- Un champ d'entrée texte + bouton "Envoyer"
- Un bouton "🎤 Parler" pour l'enregistrement vocal
- Les rappels s'affichent aussi dans la fenêtre

Architecture thread-safe :
- La boucle principale Tkinter tourne dans le thread principal
- Les tâches longues (appels API, micro, rappels) tournent dans des threads séparés
- Communication via queue.Queue() partagée
- root.after() vérifie périodiquement la queue pour mettre à jour l'interface
"""

import json
import threading
import time
import traceback
from pathlib import Path
from queue import Queue
from tkinter import Tk, Text, Entry, Button, Frame, Scrollbar, Label, Listbox, Toplevel, messagebox, Canvas
from tkinter import END, DISABLED, NORMAL, RIGHT, Y, X, BOTH
from tkinter import font as tkfont

# Charger les variables d'environnement depuis le fichier .env AVANT les imports de core.brain
from dotenv import load_dotenv
load_dotenv()

from core.brain import demander_a_ruspi
from core.memory import (
    DOSSIER_SESSIONS,
    charger_session,
    lister_sessions,
    nouveau_fichier_session,
    sauvegarder_session,
)
from core.rappels import verifier_rappels_en_attente
from core.voice import (
    ecouter_en_continu,
    ecouter_micro,
    parler,
    arreter_lecture_en_cours,
    pause_ecoute_continue,
    reprendre_ecoute_continue,
)


# ─────────────────────────────────────────────────────────────────────────────
# Constantes de design
# ─────────────────────────────────────────────────────────────────────────────

# Palette visuelle HUD futuriste : fond sombre, accents lumineux et lisibilité.
COULEUR_FOND = "#0a0e14"
COULEUR_PANEL = "#0d1117"
COULEUR_PANEL_2 = "#111827"
COULEUR_BORDURE = "#00d9ff"
COULEUR_TEXTE = "#dfeaf7"
COULEUR_BOUTON = "#111827"
COULEUR_BOUTON_HOVER = "#162133"
COULEUR_UTILISATEUR = "#58a6ff"  # Bleu cyan principal pour l'utilisateur.
COULEUR_RUSPI = "#39ff14"        # Vert néon pour les réponses de R.U.S.P.I.
COULEUR_RAPPEL = "#ff9d00"       # Orange/ambre pour les rappels.
COULEUR_SYSTEME = "#7dd3fc"
COULEUR_ERREUR = "#ff5f7d"
COULEUR_INDICATEUR_REPOS = "#4b5563"
COULEUR_INDICATEUR_REFLEXION = "#00d9ff"
COULEUR_INDICATEUR_ECOUTE = "#39ff14"
COULEUR_INDICATEUR_PAROLE = "#ff9d00"
LARGEUR_MIN = 700
HAUTEUR_MIN = 560
POLICES = ("Consolas", 10)
POLICE_TITRE = ("Consolas", 14, "bold")


# ─────────────────────────────────────────────────────────────────────────────
# Messages pour la queue inter-threads
# ─────────────────────────────────────────────────────────────────────────────

class MessageAffichage:
    """Structure simple pour les messages à afficher."""
    def __init__(self, type_msg, contenu, auteur=None):
        self.type = type_msg  # "utilisateur", "ruspi", "rappel", "erreur", "status"
        self.contenu = contenu
        self.auteur = auteur


# ─────────────────────────────────────────────────────────────────────────────
# Classe principale GUI
# ─────────────────────────────────────────────────────────────────────────────

class GUIRuspi:
    """Interface graphique pour R.U.S.P.I.
    
    Gère la fenêtre principale, l'affichage et la communication avec les threads
    de travail via une queue thread-safe.
    """

    def __init__(self, root: Tk):
        """Initialise l'interface graphique et les ressources."""
        self.root = root
        self.root.title("◈ R.U.S.P.I — SYSTÈME ACTIF ◈")
        self.root.geometry(f"{LARGEUR_MIN}x{HAUTEUR_MIN}")
        self.root.minsize(LARGEUR_MIN, HAUTEUR_MIN)
        self.root.configure(bg=COULEUR_FOND)

        # État de la session.
        self.chemin_session = None
        self.historique = []
        self.en_cours_de_traitement = False
        self.etat_indicateur = "repos"

        # Queue pour communication inter-threads
        self.queue_messages = Queue()

        # Threads en arrière-plan
        self.thread_rappels = None
        self.thread_micro = None
        self.thread_mains_libres = None
        self.thread_demande = None
        self.drapeau_arret = threading.Event()
        self.evenement_arret_mains_libres = None
        self.mode_mains_libres_actif = False
        self._thread_mains_libres_en_cours = False
        self.nombre_lectures = 0

        # Sélectionner une police technique disponible avec fallback universel.
        familles = set(tkfont.families())
        police_choisie = "Consolas"
        if police_choisie not in familles:
            for famille in ("Cascadia Code", "Courier New", "Segoe UI", "Arial"):
                if famille in familles:
                    police_choisie = famille
                    break
        self.police_technique = (police_choisie, 10)
        self.police_titre = (police_choisie, 14, "bold")

        # Créer l'interface
        self._creer_interface()

        # Charger ou créer une session
        self._selectionner_session()

        # Lancer la surveillance des rappels
        self._demarrer_thread_rappels()

        # Commencer à vérifier la queue
        self._verifier_queue()

        # Gérer la fermeture propre
        self.root.protocol("WM_DELETE_WINDOW", self._fermer_app)

    def _creer_interface(self) -> None:
        """Crée tous les éléments de l'interface Tkinter."""
        # Frame principal avec fond sombre et bordures lumineuses.
        frame_principal = Frame(
            self.root,
            bg=COULEUR_FOND,
            highlightbackground=COULEUR_BORDURE,
            highlightthickness=1,
            padx=10,
            pady=10,
        )
        frame_principal.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # ─────── En-tête HUD ───────
        self.header_frame = Frame(frame_principal, bg=COULEUR_FOND)
        self.header_frame.pack(fill=X, pady=(0, 8))

        self.label_titre = Label(
            self.header_frame,
            text="◈ R.U.S.P.I — SYSTÈME ACTIF ◈",
            bg=COULEUR_FOND,
            fg=COULEUR_SYSTEME,
            font=self.police_titre,
            justify="left",
        )
        self.label_titre.pack(side="left", fill=X, expand=True)

        self.canvas_indicateur = Canvas(
            self.header_frame,
            width=20,
            height=20,
            bg=COULEUR_FOND,
            highlightthickness=0,
        )
        self.canvas_indicateur.pack(side="right")
        self.indicateur_cercle = self.canvas_indicateur.create_oval(
            2, 2, 18, 18,
            fill=COULEUR_INDICATEUR_REPOS,
            outline=COULEUR_BORDURE,
            width=1,
        )
        self._mettre_a_jour_indicateur("repos")

        # ─────── Zone de conversation ───────
        self.texte_historique = Text(
            frame_principal,
            height=20,
            width=70,
            bg=COULEUR_PANEL,
            fg=COULEUR_TEXTE,
            font=self.police_technique,
            wrap="word",
            state=NORMAL,
            relief="flat",
            highlightbackground=COULEUR_BORDURE,
            highlightthickness=1,
            insertbackground=COULEUR_TEXTE,
        )
        self.texte_historique.pack(fill=BOTH, expand=True, pady=(0, 8))

        # Scrollbar pour la zone de texte.
        scrollbar = Scrollbar(self.texte_historique, bg=COULEUR_PANEL, highlightbackground=COULEUR_BORDURE)
        scrollbar.pack(side=RIGHT, fill=Y)
        self.texte_historique.config(yscrollcommand=scrollbar.set)
        scrollbar.config(command=self.texte_historique.yview)

        # Configurer les tags de couleur pour l'utilisateur, R.U.S.P.I et les messages système.
        self.texte_historique.tag_configure("utilisateur", foreground=COULEUR_UTILISATEUR, font=self.police_technique)
        self.texte_historique.tag_configure("ruspi", foreground=COULEUR_RUSPI, font=self.police_technique)
        self.texte_historique.tag_configure("rappel", foreground=COULEUR_RAPPEL, font=self.police_technique)
        self.texte_historique.tag_configure("erreur", foreground=COULEUR_ERREUR, font=self.police_technique)
        self.texte_historique.tag_configure("status", foreground=COULEUR_SYSTEME, font=(self.police_technique[0], 9))

        # ─────── Frame pour saisie ───────
        frame_saisie = Frame(frame_principal, bg=COULEUR_FOND)
        frame_saisie.pack(fill=X, pady=(0, 5))

        self.champ_entree = Entry(
            frame_saisie,
            bg=COULEUR_PANEL_2,
            fg=COULEUR_TEXTE,
            font=self.police_technique,
            insertbackground=COULEUR_TEXTE,
            relief="flat",
            highlightbackground=COULEUR_BORDURE,
            highlightthickness=1,
        )
        self.champ_entree.pack(fill=X, side="left", expand=True, padx=(0, 5))
        self.champ_entree.bind("<Return>", lambda e: self._envoyer_message())

        # Bouton d'envoi : même logique, style HUD.
        self.bouton_envoyer = Button(
            frame_saisie,
            text="Envoyer",
            bg=COULEUR_BOUTON,
            fg=COULEUR_SYSTEME,
            activebackground=COULEUR_BOUTON_HOVER,
            activeforeground=COULEUR_SYSTEME,
            font=self.police_technique,
            relief="flat",
            bd=1,
            highlightbackground=COULEUR_BORDURE,
            highlightthickness=1,
            command=self._envoyer_message,
        )
        self.bouton_envoyer.pack(side="left", padx=(0, 5))

        # Bouton micro : même logique, style HUD.
        self.bouton_micro = Button(
            frame_saisie,
            text="🎤 Parler",
            bg=COULEUR_BOUTON,
            fg=COULEUR_SYSTEME,
            activebackground=COULEUR_BOUTON_HOVER,
            activeforeground=COULEUR_SYSTEME,
            font=self.police_technique,
            relief="flat",
            bd=1,
            highlightbackground=COULEUR_BORDURE,
            highlightthickness=1,
            command=self._enregistrer_vocal,
        )
        self.bouton_micro.pack(side="left")

        # Bouton affiché uniquement pendant la lecture d'une réponse.
        self.bouton_interrompre = Button(
            frame_saisie,
            text="⏹ Interrompre",
            bg="#4d1a1a",
            fg=COULEUR_TEXTE,
            activebackground="#6d2020",
            activeforeground=COULEUR_TEXTE,
            font=self.police_technique,
            relief="flat",
            bd=1,
            highlightbackground=COULEUR_ERREUR,
            highlightthickness=1,
            command=self._interrompre_lecture,
        )

        # Bouton pour activer explicitement l'écoute continue.
        self.bouton_mains_libres = Button(
            frame_saisie,
            text="🎧 Mode mains libres : Désactivé",
            bg=COULEUR_BOUTON,
            fg=COULEUR_TEXTE,
            activebackground=COULEUR_BOUTON_HOVER,
            activeforeground=COULEUR_TEXTE,
            font=self.police_technique,
            relief="flat",
            bd=1,
            highlightbackground=COULEUR_BORDURE,
            highlightthickness=1,
            command=self._basculer_mode_mains_libres,
        )
        self.bouton_mains_libres.pack(side="left", padx=(5, 0))

        # Afficher un message de bienvenue.
        self._afficher_status("R.U.S.P.I prêt. Tapez un message ou utilisez le micro.")
        self._set_etat_affichage("repos")

    def _mettre_a_jour_indicateur(self, etat: str) -> None:
        """Met à jour la couleur du cercle d'état selon le statut courant."""
        if not hasattr(self, "canvas_indicateur") or not hasattr(self, "indicateur_cercle"):
            return

        palette = {
            "repos": (COULEUR_INDICATEUR_REPOS, "#7a8393"),
            "reflexion": (COULEUR_INDICATEUR_REFLEXION, "#aef6ff"),
            "ecoute": (COULEUR_INDICATEUR_ECOUTE, "#baffbc"),
            "parole": (COULEUR_INDICATEUR_PAROLE, "#ffd382"),
            "erreur": (COULEUR_ERREUR, "#ffc0cc"),
        }
        remplissage, contour = palette.get(etat, palette["repos"])
        self.canvas_indicateur.itemconfig(self.indicateur_cercle, fill=remplissage, outline=contour, width=2)
        self.etat_indicateur = etat

    def _afficher_status(self, message: str) -> None:
        """Affiche un message de statut dans la conversation."""
        self.texte_historique.config(state=NORMAL)
        self.texte_historique.insert(END, f"[Système] {message}\n", "status")
        self.texte_historique.see(END)
        self.texte_historique.config(state=NORMAL)

    def _set_etat_affichage(self, etat: str) -> None:
        """Met à jour l'état visuel du HUD sans modifier la logique métier."""
        self._mettre_a_jour_indicateur(etat)

    def _afficher_message(self, auteur: str, contenu: str, tag: str = "ruspi") -> None:
        """Affiche un message dans la zone de conversation avec tag de couleur."""
        self.texte_historique.config(state=NORMAL)
        if auteur:
            self.texte_historique.insert(END, f"{auteur}: ", tag)
        self.texte_historique.insert(END, f"{contenu}\n")
        self.texte_historique.see(END)
        self.texte_historique.config(state=NORMAL)

    def _selectionner_session(self) -> None:
        """Affiche une fenêtre de dialogue pour charger ou créer une session.
        
        La fenêtre est modale et bloque l'interaction avec la fenêtre principale
        jusqu'à ce que l'utilisateur fasse un choix (charger existante ou nouvelle).
        """
        sessions = lister_sessions()

        if sessions:
            # Créer et afficher la fenêtre de dialogue
            self._creer_dialogue_session(sessions)
        else:
            # Aucune session existante, créer directement une nouvelle
            self._creer_nouvelle_session()

    def _creer_dialogue_session(self, sessions: list) -> None:
        """Crée une fenêtre Toplevel modale pour sélectionner une session.
        
        Args:
            sessions: Liste des noms de sessions disponibles.
        """
        # Créer la fenêtre modale
        dialogue = Toplevel(self.root)
        dialogue.title("Charger une session")
        dialogue.geometry("500x400")
        dialogue.configure(bg=COULEUR_FOND)
        dialogue.resizable(False, False)
        
        # Rendre la fenêtre modale
        dialogue.transient(self.root)
        dialogue.grab_set()

        # Centrer la fenêtre sur l'écran
        self._centrer_fenetre(dialogue, 500, 400)

        # Label titre
        label_titre = Label(
            dialogue,
            text="Charger une session",
            bg=COULEUR_FOND,
            fg=COULEUR_TEXTE,
            font=self.police_titre,
        )
        label_titre.pack(pady=10)

        # Label instructions
        label_instructions = Label(
            dialogue,
            text="Sélectionnez une session existante ou créez-en une nouvelle.",
            bg=COULEUR_FOND,
            fg=COULEUR_TEXTE,
            font=self.police_technique,
            wraplength=450,
        )
        label_instructions.pack(pady=(0, 10))

        # Frame pour la Listbox et sa scrollbar
        frame_listbox = Frame(dialogue, bg=COULEUR_FOND)
        frame_listbox.pack(fill=BOTH, expand=True, padx=10, pady=10)

        # Scrollbar
        scrollbar = Scrollbar(frame_listbox)
        scrollbar.pack(side=RIGHT, fill=Y)

        # Listbox avec les sessions
        listbox = Listbox(
            frame_listbox,
            bg="#2a2a3e",
            fg=COULEUR_TEXTE,
            font=self.police_technique,
            yscrollcommand=scrollbar.set,
            highlightthickness=0,
        )
        listbox.pack(fill=BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        # Remplir la Listbox avec les sessions
        for session in sessions:
            listbox.insert("end", session)

        # Sélectionner le premier élément par défaut
        if sessions:
            listbox.selection_set(0)
            listbox.see(0)

        # Variable pour stocker le choix de l'utilisateur
        choix = {"session": None, "nouvelle": False}

        def _charger_selection():
            """Charge la session sélectionnée et ferme le dialogue."""
            selection = listbox.curselection()
            if selection:
                choix["session"] = sessions[selection[0]]
            dialogue.destroy()

        def _creer_nouvelle():
            """Crée une nouvelle session et ferme le dialogue."""
            choix["nouvelle"] = True
            dialogue.destroy()

        # Frame pour les boutons
        frame_boutons = Frame(dialogue, bg=COULEUR_FOND)
        frame_boutons.pack(fill=X, padx=10, pady=10)

        # Bouton "Charger la sélection"
        bouton_charger = Button(
            frame_boutons,
            text="Charger la sélection",
            bg=COULEUR_BOUTON,
            fg=COULEUR_TEXTE,
            activebackground=COULEUR_BOUTON_HOVER,
            activeforeground=COULEUR_TEXTE,
            font=self.police_technique,
            command=_charger_selection,
        )
        bouton_charger.pack(side="left", padx=(0, 5), expand=True, fill=X)

        # Bouton "Nouvelle conversation"
        bouton_nouvelle = Button(
            frame_boutons,
            text="Nouvelle conversation",
            bg=COULEUR_BOUTON,
            fg=COULEUR_TEXTE,
            activebackground=COULEUR_BOUTON_HOVER,
            activeforeground=COULEUR_TEXTE,
            font=self.police_technique,
            command=_creer_nouvelle,
        )
        bouton_nouvelle.pack(side="left", expand=True, fill=X)

        # Attendre que la fenêtre se ferme (bloc d'exécution)
        self.root.wait_window(dialogue)

        # Traiter le choix de l'utilisateur
        if choix["nouvelle"]:
            self._creer_nouvelle_session()
        elif choix["session"]:
            session_selectionnee = choix["session"]
            chemin = DOSSIER_SESSIONS / session_selectionnee
            self.historique = charger_session(str(chemin))
            self.chemin_session = str(chemin)
            self._afficher_status(f"Session chargée: {session_selectionnee}")
            # Afficher l'historique dans la zone de conversation
            for item in self.historique:
                auteur = "Vous" if item["role"] == "user" else "R.U.S.P.I"
                tag = "utilisateur" if item["role"] == "user" else "ruspi"
                self._afficher_message(auteur, item["content"], tag)
        else:
            # L'utilisateur a fermé la fenêtre sans rien choisir
            self._creer_nouvelle_session()

    def _centrer_fenetre(self, fenetre: Toplevel, largeur: int, hauteur: int) -> None:
        """Centre une fenêtre Tkinter sur l'écran.
        
        Args:
            fenetre: La fenêtre Tkinter à centrer.
            largeur: Largeur de la fenêtre en pixels.
            hauteur: Hauteur de la fenêtre en pixels.
        """
        # Récupérer les dimensions de l'écran
        largeur_ecran = fenetre.winfo_screenwidth()
        hauteur_ecran = fenetre.winfo_screenheight()

        # Calculer les coordonnées de centrage
        x = (largeur_ecran - largeur) // 2
        y = (hauteur_ecran - hauteur) // 2

        # Positionner la fenêtre
        fenetre.geometry(f"+{x}+{y}")

    def _creer_nouvelle_session(self) -> None:
        """Crée une nouvelle session."""
        nom_fichier = nouveau_fichier_session()
        self.chemin_session = DOSSIER_SESSIONS / nom_fichier
        self.historique = []
        self._afficher_status(f"Nouvelle session créée.")

    def _envoyer_message(self) -> None:
        """Envoie le message tapé par l'utilisateur."""
        message = self.champ_entree.get().strip()
        if not message or self.en_cours_de_traitement:
            return

        # Afficher le message de l'utilisateur
        self._afficher_message("Vous", message, "utilisateur")
        self.historique.append({"role": "user", "content": message})

        # Vider le champ d'entrée
        self.champ_entree.delete(0, "end")

        # Marquer comme en cours de traitement et désactiver les boutons
        self.en_cours_de_traitement = True
        self._set_etat_affichage("reflexion")
        self._actualiser_etat_boutons()
        self._afficher_status("R.U.S.P.I réfléchit...")

        # Lancer l'appel API dans un thread séparé
        self.thread_demande = threading.Thread(
            target=self._thread_demander_a_ruspi,
            args=(message,),
            daemon=True,
        )
        self.thread_demande.start()

    def _enregistrer_vocal(self) -> None:
        """Enregistre et transcrit l'audio du micro."""
        if self.en_cours_de_traitement:
            messagebox.showwarning("Occupé", "R.U.S.P.I est en train de réfléchir, patientez...")
            return

        self._afficher_status("Écoute en cours... (6 secondes)")
        self.bouton_envoyer.config(state=DISABLED)
        self.bouton_micro.config(state=DISABLED)
        self.en_cours_de_traitement = True
        self._set_etat_affichage("ecoute")
        self._actualiser_etat_boutons()

        # Lancer l'enregistrement dans un thread séparé
        self.thread_micro = threading.Thread(
            target=self._thread_ecouter_micro,
            daemon=True,
        )
        self.thread_micro.start()

    def _actualiser_etat_boutons(self) -> None:
        """Adapte les boutons selon l'écoute et le traitement en cours."""
        self.bouton_envoyer.config(
            state=DISABLED if self.en_cours_de_traitement else NORMAL
        )
        self.bouton_micro.config(
            state=DISABLED if self.en_cours_de_traitement or self.mode_mains_libres_actif else NORMAL
        )
        if hasattr(self, "bouton_mains_libres"):
            self.bouton_mains_libres.config(
                state=DISABLED if self._thread_mains_libres_en_cours else NORMAL
            )

    def _interrompre_lecture(self) -> None:
        """Point d'entrée explicite du clic sur le bouton Arrêter.

        Ce wrapper sert à confirmer visuellement dans le terminal que le clic
        du bouton déclenche bien la fonction d'arrêt de lecture, puis il appelle
        la fonction métier de core.voice sans modifier son comportement.
        """
        print("[DEBUG] CLIC BOUTON INTERROMPRE -> arreter_lecture_en_cours()")
        arreter_lecture_en_cours()

    def _basculer_mode_mains_libres(self) -> None:
        """Active ou arrête l'écoute continue sur demande de l'utilisateur."""
        # Gare antifaille : un seul thread d'écoute continue doit exister à la fois.
        if self._thread_mains_libres_en_cours and not self.mode_mains_libres_actif:
            print("[DEBUG] _basculer_mode_mains_libres() : un thread mains libres est déjà actif, ignore le double clic.")
            return

        if self.mode_mains_libres_actif:
            self.mode_mains_libres_actif = False
            if self.evenement_arret_mains_libres:
                self.evenement_arret_mains_libres.set()
            self.bouton_mains_libres.config(
                text="🎧 Mode mains libres : Désactivé", bg=COULEUR_BOUTON, state=DISABLED
            )
            self._set_etat_affichage("repos")
            self._actualiser_etat_boutons()
            self._afficher_status("Mode mains libres arrêté.")
            return

        # Désactiver le bouton pendant la transition pour éviter le double-clic.
        self.bouton_mains_libres.config(state=DISABLED)
        self._thread_mains_libres_en_cours = True
        self.mode_mains_libres_actif = True
        self.evenement_arret_mains_libres = threading.Event()
        self._set_etat_affichage("ecoute")
        self.bouton_mains_libres.config(
            text="🎧 Mode mains libres : Activé", bg=COULEUR_RUSPI
        )
        self._actualiser_etat_boutons()
        self._afficher_status("🎧 Écoute active... Parlez naturellement.")
        self.thread_mains_libres = threading.Thread(
            target=self._thread_ecouter_en_continu,
            args=(self.evenement_arret_mains_libres,),
            daemon=True,
        )
        self.thread_mains_libres.start()

    def _thread_ecouter_en_continu(self, evenement_arret: threading.Event) -> None:
        """Thread d'écoute continue (ne pas appeler depuis le thread principal)."""
        try:
            ecouter_en_continu(
                lambda texte: self.queue_messages.put(
                    MessageAffichage("texte_micro", texte)
                ),
                evenement_arret,
            )
        except Exception as erreur:
            if not evenement_arret.is_set():
                self.queue_messages.put(
                    MessageAffichage("erreur_mains_libres", f"Erreur écoute continue: {erreur}")
                )
        finally:
            self._thread_mains_libres_en_cours = False
            self.mode_mains_libres_actif = False
            if hasattr(self, "bouton_mains_libres"):
                self.bouton_mains_libres.config(
                    text="🎧 Mode mains libres : Désactivé", bg=COULEUR_BOUTON, state=NORMAL
                )
            self._actualiser_etat_boutons()

    def _thread_ecouter_micro(self) -> None:
        """Thread d'enregistrement vocal (ne pas appeler depuis le main thread)."""
        try:
            texte_transcrit = ecouter_micro(duree_secondes=6)
            self.queue_messages.put(MessageAffichage("texte_micro", texte_transcrit))
        except Exception as erreur:
            self.queue_messages.put(
                MessageAffichage("erreur", f"Erreur micro: {str(erreur)}")
            )

    def _thread_demander_a_ruspi(self, message: str) -> None:
        """Thread pour appeler l'API Gemini (ne pas appeler depuis le main thread).
        
        Passe une COPIE de l'historique à demander_a_ruspi() pour éviter les
        conditions de course si l'historique est modifié par le thread principal
        pendant que cet appel s'exécute.
        """
        try:
            # Faire une copie de l'historique pour éviter les problèmes de concurrence
            historique_copie = list(self.historique)
            reponse = demander_a_ruspi(message, historique_copie)
            self.queue_messages.put(MessageAffichage("reponse_ruspi", reponse))
        except Exception as erreur:
            # Afficher le message d'erreur et le traceback complet pour déboggage
            texte_erreur = f"Erreur API: {str(erreur)}"
            print(f"[DEBUG] Exception dans _thread_demander_a_ruspi : {texte_erreur}")
            print(f"[DEBUG] Traceback complet :")
            traceback.print_exc()
            self.queue_messages.put(MessageAffichage("erreur", texte_erreur))

    def _verifier_queue(self) -> None:
        """Vérifie périodiquement la queue et met à jour l'interface.
        
        Cette fonction est appelée régulièrement (tous les 100ms) depuis le
        thread principal Tkinter pour traiter les messages des threads
        d'arrière-plan.
        """
        while not self.queue_messages.empty():
            msg = self.queue_messages.get()

            if msg.type == "reponse_ruspi":
                # Réponse de Gemini reçue
                self._afficher_message("R.U.S.P.I", msg.contenu, "ruspi")
                self.historique.append({"role": "assistant", "content": msg.contenu})
                sauvegarder_session(str(self.chemin_session), self.historique)
                self._afficher_status("R.U.S.P.I a parlé.")
                # Lire la réponse à voix haute avec gestion de la pause si mains libres actif.
                self._set_etat_affichage("parole")
                threading.Thread(
                    target=self._parler_avec_pause_si_mains_libres,
                    args=(msg.contenu,),
                    daemon=True
                ).start()
                self.en_cours_de_traitement = False
                self._actualiser_etat_boutons()

            elif msg.type == "texte_micro":
                # Texte transcrit du micro
                self._afficher_message("Vous", msg.contenu, "utilisateur")
                self.historique.append({"role": "user", "content": msg.contenu})
                self._set_etat_affichage("reflexion")
                self._afficher_status("R.U.S.P.I réfléchit...")
                self._demander_a_ruspi_depuis_queue_micro(msg.contenu)

            elif msg.type == "rappel":
                # Rappel déclenché
                self._afficher_message("📌 Rappel", msg.contenu, "rappel")
                # Parler du rappel en arrière-plan avec gestion de la pause si mains libres actif
                threading.Thread(
                    target=self._parler_avec_pause_si_mains_libres,
                    args=(msg.contenu,),
                    daemon=True
                ).start()

            elif msg.type == "erreur":
                # Erreur
                self._afficher_message("❌ Erreur", msg.contenu, "erreur")
                self._set_etat_affichage("erreur")
                self.en_cours_de_traitement = False
                self._actualiser_etat_boutons()

            elif msg.type == "erreur_mains_libres":
                # Une erreur audio arrête le mode pour éviter une interface incohérente.
                self._afficher_message("❌ Erreur", msg.contenu, "erreur")
                self.mode_mains_libres_actif = False
                self._set_etat_affichage("erreur")
                self._actualiser_etat_boutons()
                self.bouton_mains_libres.config(
                    text="🎧 Mode mains libres : Désactivé", bg=COULEUR_BOUTON
                )

            elif msg.type == "parole_debut":
                self.nombre_lectures += 1
                self._set_etat_affichage("parole")
                if self.nombre_lectures == 1:
                    self.bouton_interrompre.pack(side="left", padx=(5, 0))

            elif msg.type == "parole_fin":
                self.nombre_lectures = max(0, self.nombre_lectures - 1)
                self._set_etat_affichage("ecoute" if self.mode_mains_libres_actif else "repos")
                if self.nombre_lectures == 0:
                    self.bouton_interrompre.pack_forget()

            elif msg.type == "status":
                # Message de statut
                self._afficher_status(msg.contenu)

        # Reprogrammer la vérification dans 100ms
        self.root.after(100, self._verifier_queue)

    def _demander_a_ruspi_depuis_queue(self) -> None:
        """Lance l'appel API pour le dernier message utilisateur."""
        self.thread_demande = threading.Thread(
            target=self._thread_demander_a_ruspi,
            args=(self.historique[-1]["content"],),
            daemon=True,
        )
        self.thread_demande.start()

    def _demander_a_ruspi_depuis_queue_micro(self, message: str) -> None:
        """Lance l'appel API après transcription vocale."""
        self.thread_demande = threading.Thread(
            target=self._thread_demander_a_ruspi,
            args=(message,),
            daemon=True,
        )
        self.thread_demande.start()

    def _demarrer_thread_rappels(self) -> None:
        """Lance le thread de surveillance des rappels."""
        self.thread_rappels = threading.Thread(
            target=self._thread_surveiller_rappels,
            daemon=True,
        )
        self.thread_rappels.start()

    def _thread_surveiller_rappels(self) -> None:
        """Thread de surveillance des rappels (ne pas appeler depuis le main thread)."""
        while not self.drapeau_arret.is_set():
            try:
                rappels_declenches = verifier_rappels_en_attente()
                for texte_rappel in rappels_declenches:
                    # Envoyer le rappel à la queue pour affichage dans la GUI
                    self.queue_messages.put(MessageAffichage("rappel", texte_rappel))
                    # Aussi lancer une notification système si possible
                    try:
                        from plyer import notification
                        notification.notify(
                            title="R.U.S.P.I - Rappel",
                            message=texte_rappel,
                            app_name="R.U.S.P.I",
                            timeout=10,
                        )
                    except Exception:
                        pass
            except Exception as erreur:
                # Ne pas faire crasher le programme
                pass

            # Vérifier les rappels toutes les 30 secondes
            self.drapeau_arret.wait(30)

    def _parler_avec_pause_si_mains_libres(self, texte: str) -> None:
        """Lance la synthèse vocale en mettant en pause l'écoute continue si active.
        
        Cette fonction est exécutée dans un thread séparé pour éviter de bloquer
        l'interface. Elle met en pause le mode mains libres juste avant de parler,
        puis le reprend après la fin de la lecture audio.
        
        Args:
            texte: Le texte à lire à voix haute.
        """
        # Mettre en pause l'écoute continue si le mode mains libres est actif.
        # Cela évite que le micro capture la voix synthétisée et la traite comme
        # une nouvelle entrée utilisateur, et réduit la latence audio.
        if self.mode_mains_libres_actif:
            pause_ecoute_continue()
        
        try:
            # Lire le texte à voix haute
            self.queue_messages.put(MessageAffichage("parole_debut", None))
            parler(texte)
        finally:
            self.queue_messages.put(MessageAffichage("parole_fin", None))
            # Toujours reprendre l'écoute, même en cas d'erreur
            if self.mode_mains_libres_actif:
                reprendre_ecoute_continue()

    def _fermer_app(self) -> None:
        """Ferme l'application proprement."""
        # Signaler l'arrêt
        self.drapeau_arret.set()
        if self.evenement_arret_mains_libres:
            self.evenement_arret_mains_libres.set()

        # Attendre la fin des threads avec timeout
        if self.thread_rappels and self.thread_rappels.is_alive():
            self.thread_rappels.join(timeout=2)
        if self.thread_mains_libres and self.thread_mains_libres.is_alive():
            self.thread_mains_libres.join(timeout=2)

        # Détruire la fenêtre
        self.root.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Fonction principale
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Point d'entrée pour l'interface graphique."""
    root = Tk()
    app = GUIRuspi(root)
    root.mainloop()


if __name__ == "__main__":
    main()
