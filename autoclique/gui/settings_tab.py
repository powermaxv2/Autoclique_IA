"""Onglet « Paramètres »."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ..core.keys import hotkey_label
from ..core.screen import available_engine
from ..core.settings import DEFAULT_HOTKEYS, HOTKEY_LABELS, Settings
from .widgets import get_int, number_box, tooltip


class SettingsTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, padding=14)
        self.app = app
        self.hotkey_labels = {}
        self._build()
        self.load()

    def _build(self) -> None:
        self.columnconfigure(0, weight=3, uniform="col")
        self.columnconfigure(1, weight=2, uniform="col")

        box = ttk.LabelFrame(self, text="Raccourcis globaux", padding=12)
        box.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        ttk.Label(box, text="Actifs même quand Autoclique est en arrière-plan ou réduit.",
                  style="Muted.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))
        for row, binding in enumerate(DEFAULT_HOTKEYS, start=1):
            ttk.Label(box, text=HOTKEY_LABELS[binding]).grid(row=row, column=0, sticky="w", pady=4)
            label = ttk.Label(box, style="Strong.TLabel", width=16)
            label.grid(row=row, column=1, sticky="w", padx=16)
            self.hotkey_labels[binding] = label
            ttk.Button(box, text="Modifier…", command=lambda b=binding: self.app.edit_global_hotkey(b)).grid(
                row=row, column=2, padx=3)
            reset = ttk.Button(box, text="Par défaut", command=lambda b=binding: self._reset_hotkey(b))
            reset.grid(row=row, column=3, padx=3)
            tooltip(reset, f"Remettre {hotkey_label(DEFAULT_HOTKEYS[binding])}")
        box.columnconfigure(4, weight=1)

        box = ttk.LabelFrame(self, text="Comportement", padding=12)
        box.grid(row=1, column=0, rowspan=2, sticky="nsew", padx=(0, 7), pady=(0, 10))
        self.minimize = tk.BooleanVar()
        self.topmost = tk.BooleanVar()
        self.failsafe = tk.BooleanVar()
        self.confirm = tk.BooleanVar()
        for text, var, tip in (
            ("Réduire la fenêtre pendant l'exécution", self.minimize,
             "Pendant l'auto-clic, la lecture et l'enregistrement. La fenêtre réapparaît "
             "à la fin d'un enregistrement."),
            ("Garder la fenêtre au premier plan", self.topmost, ""),
            ("Arrêt de sécurité : souris dans le coin supérieur gauche", self.failsafe,
             "Plaquer le curseur dans le coin supérieur gauche de l'écran principal arrête "
             "l'auto-clic ou la macro en cours."),
            ("Demander confirmation avant de supprimer une macro", self.confirm, ""),
        ):
            check = ttk.Checkbutton(box, text=text, variable=var, command=self._changed)
            check.pack(anchor="w", pady=2)
            if tip:
                tooltip(check, tip)
        self.countdown = tk.StringVar()
        self.default_delay = tk.StringVar()
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(8, 2))
        ttk.Label(row, text="Compte à rebours avant lecture / enregistrement").pack(side="left")
        number_box(row, self.countdown, 0, 60, width=5).pack(side="left", padx=6)
        ttk.Label(row, text="s").pack(side="left")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=2)
        ttk.Label(row, text="Délai par défaut des nouvelles actions").pack(side="left")
        number_box(row, self.default_delay, 0, 60000, width=7, increment=10).pack(side="left", padx=6)
        ttk.Label(row, text="ms").pack(side="left")
        for var in (self.countdown, self.default_delay):
            var.trace_add("write", lambda *_a: self._changed())

        box = ttk.LabelFrame(self, text="Apparence", padding=12)
        box.grid(row=1, column=1, sticky="nsew", padx=(7, 0), pady=(0, 10))
        self.theme = tk.StringVar()
        row = ttk.Frame(box)
        row.pack(anchor="w")
        ttk.Label(row, text="Thème").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(row, text="Sombre", value="dark", variable=self.theme,
                        command=self._theme_changed).pack(side="left")
        ttk.Radiobutton(row, text="Clair", value="light", variable=self.theme,
                        command=self._theme_changed).pack(side="left", padx=(12, 0))

        box = ttk.LabelFrame(self, text="Données", padding=12)
        box.grid(row=2, column=1, sticky="nsew", padx=(7, 0), pady=(0, 10))
        ttk.Label(box, text="Dossier des macros et des paramètres :").pack(anchor="w")
        self.folder_label = ttk.Label(box, style="Muted.TLabel", wraplength=380, justify="left")
        self.folder_label.pack(anchor="w", pady=(2, 8))
        row = ttk.Frame(box)
        row.pack(anchor="w")
        ttk.Button(row, text="Ouvrir le dossier", command=self.app.open_data_folder).pack(side="left")
        ttk.Button(row, text="Ouvrir le journal", command=self.app.open_log_file).pack(side="left", padx=6)

        box = ttk.LabelFrame(self, text="Reconnaissance d'image", padding=12)
        box.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 10))
        engine = available_engine()
        if engine == "opencv":
            text = "Moteur : OpenCV (rapide)."
        else:
            text = ("Moteur : NumPy (intégré). Pour des recherches plus rapides sur de grands écrans, "
                    "installez OpenCV :  pip install opencv-python-headless")
        ttk.Label(box, text=text, wraplength=860, justify="left").pack(anchor="w")
        ttk.Label(box, text="Astuce : limitez la zone de recherche d'une action pour accélérer la détection. "
                            "Les images doivent être capturées avec la même mise à l'échelle d'affichage "
                            "que lors de la lecture.", style="Muted.TLabel", wraplength=860,
                  justify="left").pack(anchor="w", pady=(4, 0))

        bottom = ttk.Frame(self)
        bottom.grid(row=4, column=0, columnspan=2, sticky="ew")
        ttk.Button(bottom, text="Rétablir tous les paramètres par défaut",
                   command=self._reset_all).pack(side="left")

    def load(self) -> None:
        settings = self.app.settings
        self._loading = True
        try:
            self.minimize.set(settings.minimize_on_run)
            self.topmost.set(settings.always_on_top)
            self.failsafe.set(settings.failsafe)
            self.confirm.set(settings.confirm_delete)
            self.countdown.set(str(settings.start_countdown))
            self.default_delay.set(str(settings.default_delay))
            self.theme.set(settings.theme)
        finally:
            self._loading = False
        self.refresh_hotkeys()
        self.folder_label.configure(text=str(self.app.data_folder))

    def refresh_hotkeys(self) -> None:
        for binding, label in self.hotkey_labels.items():
            label.configure(text=hotkey_label(self.app.settings.hotkeys.get(binding, "")))

    def _changed(self) -> None:
        if getattr(self, "_loading", False):
            return
        settings = self.app.settings
        settings.minimize_on_run = bool(self.minimize.get())
        settings.always_on_top = bool(self.topmost.get())
        settings.failsafe = bool(self.failsafe.get())
        settings.confirm_delete = bool(self.confirm.get())
        settings.start_countdown = get_int(self.countdown, 0, 0, 60)
        settings.default_delay = get_int(self.default_delay, 100, 0, 60000)
        self.app.apply_window_settings()
        self.app.save_settings_soon()

    def _theme_changed(self) -> None:
        self.app.set_theme(self.theme.get())

    def _reset_hotkey(self, binding: str) -> None:
        self.app.set_global_hotkey(binding, DEFAULT_HOTKEYS[binding])

    def _reset_all(self) -> None:
        if not messagebox.askyesno("Paramètres", "Rétablir tous les paramètres par défaut ?\n"
                                                 "(Vos macros ne sont pas modifiées.)", parent=self):
            return
        defaults = Settings()
        defaults.last_macro = self.app.settings.last_macro
        defaults.geometry = self.app.settings.geometry
        self.app.replace_settings(defaults)
