"""Onglet « Aide » : présentation, raccourcis et conseils."""

from __future__ import annotations

import platform
import sys
import tkinter as tk
import webbrowser
from tkinter import ttk

from .. import APP_NAME, REPO_URL, __version__
from ..core.keys import hotkey_label
from ..core.settings import HOTKEY_LABELS
from .theme import palette, style_text_widget

GUIDE = [
    ("Auto-clic", [
        "Réglez l'intervalle, le bouton et la position, puis cliquez sur « Démarrer » "
        "ou utilisez le raccourci global.",
        "« Plusieurs points » clique à tour de rôle sur chaque position de la liste.",
        "Le mode « maintenir » clique tant que le raccourci reste enfoncé (idéal avec un bouton "
        "latéral de souris).",
    ]),
    ("Enregistrer une macro", [
        "Cliquez sur « Enregistrer » (ou appuyez sur le raccourci), faites vos actions, puis "
        "appuyez de nouveau sur le raccourci pour arrêter.",
        "« Simplifier » transforme appui + relâchement en clics et appuis de touche lisibles.",
        "Décochez « Mouvements » pour ne garder que les clics : la souris sautera d'un point à l'autre.",
    ]),
    ("Modifier une macro", [
        "Double-cliquez sur une action pour la modifier ; clic droit pour le menu complet.",
        "Sélectionnez des actions puis « Ajouter > Contrôle > Répéter » pour les mettre en boucle ; "
        "même principe avec « Si une image est visible ».",
        "Ctrl+Z / Ctrl+Y : annuler / rétablir. Ctrl+C / Ctrl+V : copier / coller, même entre macros.",
        "Les modifications sont enregistrées automatiquement.",
    ]),
    ("Reconnaissance d'image et de couleur", [
        "« Cliquer sur une image » cherche une image à l'écran et clique dessus, où qu'elle soit.",
        "Capturez l'image directement depuis l'écran, puis utilisez « Tester maintenant ».",
        "Si l'image n'est pas trouvée, baissez un peu la ressemblance minimale (85 % par exemple).",
    ]),
    ("Sécurité", [
        "Le raccourci d'arrêt d'urgence stoppe tout, à tout moment.",
        "Plaquer la souris dans le coin supérieur gauche de l'écran arrête aussi l'exécution "
        "(désactivable dans les paramètres).",
        "À la fin ou à l'arrêt d'une macro, toutes les touches et boutons encore enfoncés sont relâchés.",
    ]),
]


class AboutTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, padding=14)
        self.app = app
        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, style="Title.TLabel").pack(side="left")
        ttk.Label(header, text=f"version {__version__}", style="Muted.TLabel").pack(side="left", padx=10, pady=(8, 0))
        link = ttk.Label(header, text="Page du projet ↗", style="Muted.TLabel", cursor="hand2")
        link.pack(side="right")
        link.bind("<Button-1>", lambda _e: webbrowser.open(REPO_URL))
        ttk.Label(self, text="Auto-clicker et enregistreur de macros : souris, clavier, boucles, "
                             "conditions et reconnaissance d'image.", style="Muted.TLabel").pack(anchor="w", pady=(2, 10))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", padx=14, pady=10, height=20, cursor="arrow", font="AppBody")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.refresh()

    def refresh(self) -> None:
        text = self.text
        style_text_widget(text)
        pal = palette()
        text.configure(state="normal")
        text.delete("1.0", "end")
        text.tag_configure("h", font="AppSubtitle", spacing1=10, spacing3=4)
        text.tag_configure("item", lmargin1=12, lmargin2=26, spacing1=2)
        text.tag_configure("key", font="AppStrong", foreground=pal["accent"])
        text.tag_configure("muted", foreground=pal["muted"])
        text.insert("end", "Raccourcis globaux\n", ("h",))
        for binding, label in HOTKEY_LABELS.items():
            text.insert("end", "•  ", ("item",))
            text.insert("end", hotkey_label(self.app.settings.hotkeys.get(binding, "")), ("item", "key"))
            text.insert("end", f"  —  {label}\n", ("item",))
        for title, items in GUIDE:
            text.insert("end", f"{title}\n", ("h",))
            for item in items:
                text.insert("end", f"•  {item}\n", ("item",))
        text.insert("end", "Configuration\n", ("h",))
        engine = "OpenCV" if self.app.image_engine() == "opencv" else "NumPy"
        details = [
            f"Python {platform.python_version()} · Tk {tk.TkVersion} · {platform.system()} {platform.release()}",
            f"Recherche d'image : {engine}",
            f"Données : {self.app.data_folder}",
        ]
        if sys.platform.startswith("linux"):
            details.append("Linux : une session X11 est nécessaire (Wayland n'est pas pris en charge).")
        if sys.platform == "darwin":
            details.append("macOS : autorisez l'application dans Confidentialité et sécurité > "
                           "Accessibilité et Surveillance de l'entrée.")
        for line in details:
            text.insert("end", f"•  {line}\n", ("item", "muted"))
        text.configure(state="disabled")
