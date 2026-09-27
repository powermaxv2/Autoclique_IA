"""Onglet « Journal » : messages de l'application (fins de lecture, erreurs…)."""

from __future__ import annotations

import logging
import time
import tkinter as tk
from tkinter import ttk

from .theme import palette, style_text_widget

MAX_LINES = 2000


class LogTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, padding=14)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Journal des événements", style="Subtitle.TLabel").pack(side="left")
        ttk.Button(bar, text="Ouvrir le fichier journal", command=app.open_log_file).pack(side="right")
        ttk.Button(bar, text="Effacer", command=self.clear).pack(side="right", padx=6)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="word", height=20, state="disabled", font="AppMono",
                            padx=8, pady=6)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.refresh_theme()

    def refresh_theme(self) -> None:
        style_text_widget(self.text)
        pal = palette()
        self.text.tag_configure("WARNING", foreground=pal["warn"])
        self.text.tag_configure("ERROR", foreground=pal["error"])
        self.text.tag_configure("time", foreground=pal["muted"])

    def append(self, level: int, message: str) -> None:
        tag = "ERROR" if level >= logging.ERROR else "WARNING" if level >= logging.WARNING else ""
        self.text.configure(state="normal")
        self.text.insert("end", time.strftime("%H:%M:%S  "), ("time",))
        self.text.insert("end", message + "\n", (tag,) if tag else ())
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > MAX_LINES:
            self.text.delete("1.0", f"{lines - MAX_LINES}.0")
        self.text.configure(state="disabled")
        self.text.see("end")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
