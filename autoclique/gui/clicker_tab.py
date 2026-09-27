"""Onglet « Auto-clic »."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import List

from ..core.actions import COUNT_CHOICES
from ..core.clicker import ClickerConfig
from ..core.keys import MOUSE_BUTTONS, hotkey_label, key_label, normalize_key
from .dialogs import capture_key
from .widgets import (
    format_number,
    get_float,
    get_int,
    number_box,
    number_entry,
    readonly_combobox,
    set_enabled,
    tooltip,
)

BUTTON_LABELS = list(MOUSE_BUTTONS.values())
BUTTON_VALUES = list(MOUSE_BUTTONS)
COUNT_LABELS = [label for _v, label in COUNT_CHOICES]


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


class ClickerTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, padding=14)
        self.app = app
        self.points: List[List[int]] = []
        self._loading = False
        self._make_vars()
        self._build()
        self.load_config(app.settings.clicker)
        for var in self._all_vars:
            var.trace_add("write", lambda *_a: self._changed())

    # --- Variables -----------------------------------------------------------------

    def _make_vars(self) -> None:
        self.hours = tk.StringVar(value="0")
        self.minutes = tk.StringVar(value="0")
        self.seconds = tk.StringVar(value="0")
        self.millis = tk.StringVar(value="100")
        self.random_on = tk.BooleanVar(value=False)
        self.random_ms = tk.StringVar(value="20")
        self.mode = tk.StringVar(value="mouse")
        self.button = tk.StringVar(value=BUTTON_LABELS[0])
        self.count_kind = tk.StringVar(value=COUNT_LABELS[0])
        self.key = tk.StringVar(value="Espace")
        self.hold = tk.StringVar(value="0")
        self.repeat = tk.StringVar(value="infinite")
        self.count = tk.StringVar(value="100")
        self.duration = tk.StringVar(value="60")
        self.position = tk.StringVar(value="current")
        self.x = tk.StringVar(value="0")
        self.y = tk.StringVar(value="0")
        self.jitter_on = tk.BooleanVar(value=False)
        self.jitter = tk.StringVar(value="3")
        self.restore = tk.BooleanVar(value=False)
        self.start_delay = tk.StringVar(value="0")
        self.hotkey_mode = tk.StringVar(value="toggle")
        self._all_vars = [
            self.hours, self.minutes, self.seconds, self.millis, self.random_on, self.random_ms,
            self.mode, self.button, self.count_kind, self.key, self.hold, self.repeat, self.count,
            self.duration, self.position, self.x, self.y, self.jitter_on, self.jitter,
            self.restore, self.start_delay, self.hotkey_mode,
        ]

    # --- Construction -----------------------------------------------------------------

    def _build(self) -> None:
        self.columnconfigure(0, weight=1, uniform="col")
        self.columnconfigure(1, weight=1, uniform="col")

        # Intervalle
        box = ttk.LabelFrame(self, text="Intervalle entre deux clics", padding=12)
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 10))
        row = ttk.Frame(box)
        row.pack(anchor="w")
        for var, unit in ((self.hours, "h"), (self.minutes, "min"), (self.seconds, "s"),
                          (self.millis, "ms")):
            number_entry(row, var, width=5).pack(side="left")
            ttk.Label(row, text=unit).pack(side="left", padx=(5, 14))
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(10, 0))
        check = ttk.Checkbutton(row, text="Variation aléatoire ±", variable=self.random_on,
                                command=self._refresh_states)
        check.pack(side="left")
        tooltip(check, "Rend la cadence moins régulière (plus « humaine »).")
        self.random_box = number_box(row, self.random_ms, 0, 3_600_000, width=7, increment=10)
        self.random_box.pack(side="left", padx=6)
        ttk.Label(row, text="ms").pack(side="left")

        # Répétition
        box = ttk.LabelFrame(self, text="Répétition", padding=12)
        box.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 10))
        ttk.Radiobutton(box, text="Jusqu'à l'arrêt", value="infinite", variable=self.repeat,
                        command=self._refresh_states).pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=4)
        ttk.Radiobutton(row, text="Nombre de clics :", value="count", variable=self.repeat,
                        command=self._refresh_states).pack(side="left")
        self.count_box = number_box(row, self.count, 1, 100_000_000, width=9)
        self.count_box.pack(side="left", padx=6)
        row = ttk.Frame(box)
        row.pack(anchor="w")
        ttk.Radiobutton(row, text="Pendant :", value="duration", variable=self.repeat,
                        command=self._refresh_states).pack(side="left")
        self.duration_box = number_box(row, self.duration, 0.1, 864000, width=9, is_float=True)
        self.duration_box.pack(side="left", padx=6)
        ttk.Label(row, text="secondes").pack(side="left")

        # Action
        box = ttk.LabelFrame(self, text="Action", padding=12)
        box.grid(row=1, column=0, sticky="nsew", padx=(0, 7), pady=(0, 10))
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(0, 8))
        ttk.Radiobutton(row, text="Clic de souris", value="mouse", variable=self.mode,
                        command=self._refresh_states).pack(side="left")
        ttk.Radiobutton(row, text="Touche du clavier", value="key", variable=self.mode,
                        command=self._refresh_states).pack(side="left", padx=(16, 0))
        grid = ttk.Frame(box)
        grid.pack(anchor="w")
        ttk.Label(grid, text="Bouton").grid(row=0, column=0, sticky="w", pady=3, padx=(0, 6))
        self.button_box = readonly_combobox(grid, self.button, BUTTON_LABELS, width=20)
        self.button_box.grid(row=0, column=1, sticky="w", padx=8)
        ttk.Label(grid, text="Clic").grid(row=1, column=0, sticky="w", pady=3, padx=(0, 6))
        self.count_kind_box = readonly_combobox(grid, self.count_kind, COUNT_LABELS, width=20)
        self.count_kind_box.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(grid, text="Touche").grid(row=2, column=0, sticky="w", pady=3, padx=(0, 6))
        key_row = ttk.Frame(grid)
        key_row.grid(row=2, column=1, sticky="w", padx=8)
        self.key_entry = ttk.Entry(key_row, textvariable=self.key, width=14)
        self.key_entry.pack(side="left")
        self.key_button = ttk.Button(key_row, text="Capturer…", command=self._capture_key)
        self.key_button.pack(side="left", padx=(6, 0))
        ttk.Label(grid, text="Durée d'appui").grid(row=3, column=0, sticky="w", pady=3, padx=(0, 6))
        hold_row = ttk.Frame(grid)
        hold_row.grid(row=3, column=1, sticky="w", padx=8)
        hold = number_box(hold_row, self.hold, 0, 600000, width=7, increment=10)
        hold.pack(side="left")
        ttk.Label(hold_row, text="ms").pack(side="left", padx=(6, 0))
        tooltip(hold, "Temps pendant lequel le bouton ou la touche reste enfoncé. "
                      "Certains jeux ignorent les appuis trop brefs.")

        # Position
        box = ttk.LabelFrame(self, text="Position du clic", padding=12)
        box.grid(row=1, column=1, sticky="nsew", padx=(7, 0), pady=(0, 10))
        ttk.Radiobutton(box, text="Position actuelle du curseur", value="current",
                        variable=self.position, command=self._refresh_states).pack(anchor="w")
        row = ttk.Frame(box)
        row.pack(anchor="w", pady=4)
        ttk.Radiobutton(row, text="Position fixe", value="fixed", variable=self.position,
                        command=self._refresh_states).pack(side="left")
        ttk.Label(row, text="X").pack(side="left", padx=(10, 4))
        self.x_box = number_entry(row, self.x, width=6, negative=True)
        self.x_box.pack(side="left")
        ttk.Label(row, text="Y").pack(side="left", padx=(10, 4))
        self.y_box = number_entry(row, self.y, width=6, negative=True)
        self.y_box.pack(side="left")
        self.pick_button = ttk.Button(row, text="Choisir…", command=self._pick_fixed)
        self.pick_button.pack(side="left", padx=(8, 0))
        tooltip(self.pick_button, "Cliquez ensuite à l'endroit voulu de l'écran.")

        ttk.Radiobutton(box, text="Plusieurs points, à tour de rôle", value="points",
                        variable=self.position, command=self._refresh_states).pack(anchor="w")
        points_row = ttk.Frame(box)
        points_row.pack(fill="x", pady=(4, 0), padx=(24, 0))
        self.points_list = ttk.Treeview(points_row, columns=("n", "pos"), show="headings", height=3,
                                        selectmode="extended")
        self.points_list.heading("n", text="#")
        self.points_list.heading("pos", text="Position")
        self.points_list.column("n", width=36, anchor="center", stretch=False)
        self.points_list.column("pos", width=140)
        self.points_list.pack(side="left", fill="x", expand=True)
        buttons = ttk.Frame(points_row)
        buttons.pack(side="left", padx=(8, 0), anchor="n")
        self.add_point_button = ttk.Button(buttons, text="Ajouter…", command=self._add_point)
        self.add_point_button.pack(fill="x")
        self.remove_point_button = ttk.Button(buttons, text="Retirer", command=self._remove_points)
        self.remove_point_button.pack(fill="x", pady=4)
        self.clear_points_button = ttk.Button(buttons, text="Vider", command=self._clear_points)
        self.clear_points_button.pack(fill="x")

        row = ttk.Frame(box)
        row.pack(anchor="w", pady=(8, 0))
        self.jitter_check = ttk.Checkbutton(row, text="Décalage aléatoire ±", variable=self.jitter_on,
                                            command=self._refresh_states)
        self.jitter_check.pack(side="left")
        self.jitter_box = number_box(row, self.jitter, 0, 500, width=5)
        self.jitter_box.pack(side="left", padx=6)
        ttk.Label(row, text="px").pack(side="left")
        self.restore_check = ttk.Checkbutton(box, text="Remettre le curseur à sa place après chaque clic",
                                             variable=self.restore)
        self.restore_check.pack(anchor="w", pady=(4, 0))

        # Démarrage
        box = ttk.LabelFrame(self, text="Démarrage", padding=12)
        box.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(0, 12))
        row = ttk.Frame(box)
        row.pack(fill="x")
        ttk.Label(row, text="Délai avant le premier clic").pack(side="left")
        number_box(row, self.start_delay, 0, 3600, width=6, is_float=True).pack(side="left", padx=6)
        ttk.Label(row, text="s").pack(side="left")
        ttk.Separator(row, orient="vertical").pack(side="left", fill="y", padx=16)
        ttk.Label(row, text="Raccourci :").pack(side="left")
        self.hotkey_label = ttk.Label(row, style="Strong.TLabel")
        self.hotkey_label.pack(side="left", padx=6)
        ttk.Button(row, text="Modifier…",
                   command=lambda: self.app.edit_global_hotkey("clicker")).pack(side="left")
        row = ttk.Frame(box)
        row.pack(fill="x", pady=(8, 0))
        ttk.Radiobutton(row, text="Appuyer sur le raccourci pour démarrer / arrêter", value="toggle",
                        variable=self.hotkey_mode).pack(side="left")
        hold_radio = ttk.Radiobutton(row, text="Cliquer tant que le raccourci est maintenu",
                                     value="hold", variable=self.hotkey_mode)
        hold_radio.pack(side="left", padx=(16, 0))
        tooltip(hold_radio, "Pratique avec un bouton latéral de la souris : l'auto-clic "
                            "s'arrête dès que vous relâchez.")

        # Commandes
        bar = ttk.Frame(self)
        bar.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.start_button = ttk.Button(bar, text="▶  Démarrer", style="Big.Accent.TButton",
                                       command=self.app.start_clicker)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(bar, text="■  Arrêter", style="Big.TButton",
                                      command=self.app.stop_clicker)
        self.stop_button.pack(side="left", padx=10)
        stats = ttk.Frame(bar)
        stats.pack(side="right")
        self.stats_label = ttk.Label(stats, text="", style="Strong.TLabel")
        self.stats_label.pack(anchor="e")
        self.summary_label = ttk.Label(stats, text="", style="Muted.TLabel")
        self.summary_label.pack(anchor="e")
        self.update_stats(0, 0.0)
        self.set_running(False)

    # --- Interaction ------------------------------------------------------------------

    def _capture_key(self) -> None:
        ref = capture_key(self, self.app.hotkeys, "")
        if ref is not None:
            self.key.set(key_label(ref.name) if not ref.name.startswith("vk:") else ref.name)

    def _pick_fixed(self) -> None:
        def done(result):
            if result:
                self.x.set(str(result[0]))
                self.y.set(str(result[1]))
                self.position.set("fixed")
                self._refresh_states()

        self.app.pick_point(done)

    def _add_point(self) -> None:
        def done(result):
            if result:
                self.points.append([result[0], result[1]])
                self.position.set("points")
                self._refresh_points()
                self._refresh_states()
                self._changed()

        self.app.pick_point(done)

    def _remove_points(self) -> None:
        indices = sorted((int(i) for i in self.points_list.selection()), reverse=True)
        for index in indices:
            del self.points[index]
        self._refresh_points()
        self._changed()

    def _clear_points(self) -> None:
        self.points.clear()
        self._refresh_points()
        self._changed()

    def _refresh_points(self) -> None:
        self.points_list.delete(*self.points_list.get_children())
        for index, (x, y) in enumerate(self.points):
            self.points_list.insert("", "end", iid=str(index), values=(index + 1, f"({x}, {y})"))

    def _refresh_states(self) -> None:
        mouse = self.mode.get() == "mouse"
        set_enabled([self.button_box, self.count_kind_box], mouse)
        set_enabled([self.key_entry, self.key_button], not mouse)
        set_enabled([self.random_box], self.random_on.get())
        set_enabled([self.count_box], self.repeat.get() == "count")
        set_enabled([self.duration_box], self.repeat.get() == "duration")
        position = self.position.get()
        set_enabled([self.x_box, self.y_box], position == "fixed")
        set_enabled([self.points_list, self.remove_point_button, self.clear_points_button],
                    position == "points")
        fixed = position != "current"
        set_enabled([self.jitter_check, self.restore_check], fixed)
        set_enabled([self.jitter_box], fixed and self.jitter_on.get())

    def _changed(self) -> None:
        if self._loading:
            return
        self._refresh_states()
        try:
            config = self.read_config()
        except ValueError as exc:
            self.summary_label.configure(text=str(exc), style="Error.TLabel")
            return
        self.summary_label.configure(text=config.summary(), style="Muted.TLabel")
        self.app.settings.clicker = config
        self.app.save_settings_soon()

    # --- Configuration --------------------------------------------------------------------

    def read_config(self) -> ClickerConfig:
        interval = (((get_int(self.hours) * 60 + get_int(self.minutes)) * 60 + get_int(self.seconds)) * 1000
                    + get_int(self.millis))
        if self.mode.get() == "key":
            key = normalize_key(self.key.get())  # ValueError si la touche est inconnue
        else:
            try:
                key = normalize_key(self.key.get())
            except ValueError:
                key = "space"
        config = ClickerConfig(
            interval_ms=interval,
            random_ms=get_int(self.random_ms, 0, 0) if self.random_on.get() else 0,
            mode=self.mode.get(),
            button=BUTTON_VALUES[BUTTON_LABELS.index(self.button.get())] if self.button.get() in BUTTON_LABELS else "left",
            clicks=COUNT_LABELS.index(self.count_kind.get()) + 1 if self.count_kind.get() in COUNT_LABELS else 1,
            hold_ms=get_int(self.hold, 0, 0),
            key=key,
            repeat=self.repeat.get(),
            count=get_int(self.count, 1, 1),
            duration_s=get_float(self.duration, 60.0, 0.1),
            position=self.position.get(),
            x=get_int(self.x),
            y=get_int(self.y),
            points=[list(p) for p in self.points],
            jitter_px=get_int(self.jitter, 0, 0) if self.jitter_on.get() else 0,
            restore_cursor=bool(self.restore.get()),
            start_delay_s=get_float(self.start_delay, 0.0, 0.0),
            hotkey_mode=self.hotkey_mode.get(),
        )
        errors = config.validate()
        if errors:
            raise ValueError(errors[0])
        return config

    def load_config(self, config: ClickerConfig) -> None:
        self._loading = True
        try:
            total = max(1, int(config.interval_ms))
            hours, rest = divmod(total, 3_600_000)
            minutes, rest = divmod(rest, 60_000)
            seconds, millis = divmod(rest, 1000)
            self.hours.set(str(hours))
            self.minutes.set(str(minutes))
            self.seconds.set(str(seconds))
            self.millis.set(str(millis))
            self.random_on.set(config.random_ms > 0)
            if config.random_ms > 0:
                self.random_ms.set(str(config.random_ms))
            self.mode.set(config.mode)
            self.button.set(MOUSE_BUTTONS.get(config.button, BUTTON_LABELS[0]))
            self.count_kind.set(COUNT_LABELS[min(max(config.clicks, 1), 3) - 1])
            try:
                self.key.set(key_label(normalize_key(config.key)))
            except ValueError:
                self.key.set(config.key)
            self.hold.set(str(config.hold_ms))
            self.repeat.set(config.repeat)
            self.count.set(str(config.count))
            self.duration.set(format_number(config.duration_s))
            self.position.set(config.position)
            self.x.set(str(config.x))
            self.y.set(str(config.y))
            self.points = [list(p) for p in config.points]
            self.jitter_on.set(config.jitter_px > 0)
            if config.jitter_px > 0:
                self.jitter.set(str(config.jitter_px))
            self.restore.set(config.restore_cursor)
            self.start_delay.set(format_number(config.start_delay_s))
            self.hotkey_mode.set(config.hotkey_mode)
        finally:
            self._loading = False
        self._refresh_points()
        self._refresh_states()
        self.summary_label.configure(text=config.summary(), style="Muted.TLabel")

    # --- État d'exécution ------------------------------------------------------------------

    def refresh_hotkey(self) -> None:
        text = hotkey_label(self.app.settings.hotkeys.get("clicker", ""))
        self.hotkey_label.configure(text=text)
        suffix = f" ({text})" if text != "Aucun" else ""
        self.start_button.configure(text=f"▶  Démarrer{suffix}")

    def set_running(self, running: bool) -> None:
        set_enabled([self.start_button], not running)
        set_enabled([self.stop_button], running)

    def update_stats(self, clicks: int, elapsed: float, waiting: bool = False) -> None:
        if waiting:
            self.stats_label.configure(text="Démarrage imminent…")
            return
        rate = clicks / elapsed if elapsed > 0.2 else 0.0
        self.stats_label.configure(
            text=f"Clics : {clicks:,}".replace(",", " ") + f"   ·   Durée : {_clock(elapsed)}   ·   "
                 f"Cadence : {format_number(round(rate, 1))} clics/s")
