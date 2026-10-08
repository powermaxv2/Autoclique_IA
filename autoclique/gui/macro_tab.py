"""Onglet « Macros » : bibliothèque, éditeur d'actions, lecture et enregistrement."""

from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, List, Optional

from ..core.actions import (
    ACTION_TYPES,
    BLOCK_CLOSERS,
    CATEGORIES,
    Action,
    format_ms,
    format_seconds,
    uses_external_program,
)
from ..core.keys import hotkey_label
from ..core.macro import Macro, analyze, estimate_duration
from ..core.recorder import RecordOptions
from ..core.storage import validate_name
from .action_dialog import edit_action
from .dialogs import ask_number, ask_text, capture_hotkey
from .theme import palette
from .widgets import format_number, get_float, get_int, number_entry, set_enabled, tooltip

SPEEDS = ["0,25", "0,5", "0,75", "1", "1,5", "2", "3", "5", "10"]
UNDO_LIMIT = 100


class MacrosTab(ttk.Frame):
    def __init__(self, parent: tk.Widget, app) -> None:
        super().__init__(parent, padding=(14, 14, 14, 10))
        self.app = app
        self.macro: Optional[Macro] = None
        self.macro_name: Optional[str] = None
        self.undo_stack: List[list] = []
        self.redo_stack: List[list] = []
        self._save_job: Optional[str] = None
        self._loading = False
        self._highlight: Optional[int] = None
        self._build()
        self.refresh_library(select=app.settings.last_macro)

    # ================================================================== construction

    def _build(self) -> None:
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)
        left = ttk.Frame(paned, padding=(0, 0, 12, 0))
        right = ttk.Frame(paned)
        paned.add(left, weight=0)
        paned.add(right, weight=1)
        self._build_library(left)
        self._build_editor(right)

    def _build_library(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Mes macros", style="Subtitle.TLabel").pack(anchor="w", pady=(0, 8))
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        self.lib_tree = ttk.Treeview(frame, columns=("name", "hotkey"), show="headings",
                                     selectmode="browse", height=14)
        self.lib_tree.heading("name", text="Nom")
        self.lib_tree.heading("hotkey", text="Raccourci")
        self.lib_tree.column("name", width=150, minwidth=90)
        self.lib_tree.column("hotkey", width=66, minwidth=50)
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.lib_tree.yview)
        self.lib_tree.configure(yscrollcommand=scroll.set)
        self.lib_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.lib_tree.bind("<<TreeviewSelect>>", self._on_library_select)
        self.lib_tree.bind("<Double-1>", lambda _e: self.rename_macro())
        self.lib_tree.bind("<F2>", lambda _e: self.rename_macro())
        self.lib_tree.bind("<Delete>", lambda _e: self.delete_macro())

        buttons = ttk.Frame(parent)
        buttons.pack(fill="x", pady=(8, 0))
        buttons.columnconfigure((0, 1), weight=1)
        specs = [
            ("+ Nouvelle", self.new_macro, "Créer une macro vide"),
            ("Dupliquer", self.duplicate_macro, "Copier la macro sélectionnée"),
            ("Renommer", self.rename_macro, "Renommer (F2)"),
            ("Supprimer", self.delete_macro, "Supprimer la macro"),
            ("Importer…", self.import_macro, "Ajouter un fichier de macro (.json)"),
            ("Exporter…", self.export_macro, "Enregistrer la macro dans un fichier pour la partager"),
        ]
        self.library_buttons = {}
        for index, (text, command, tip) in enumerate(specs):
            button = ttk.Button(buttons, text=text, command=command)
            button.grid(row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)
            tooltip(button, tip)
            self.library_buttons[text] = button
        folder = ttk.Button(parent, text="Ouvrir le dossier des macros", command=self.open_folder)
        folder.pack(fill="x", pady=(6, 0), padx=2)

    def _build_editor(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.pack(fill="x")
        self.name_label = ttk.Label(header, text="", style="Title.TLabel")
        self.name_label.pack(side="left")
        hot = ttk.Frame(header)
        hot.pack(side="right")
        ttk.Label(hot, text="Raccourci de la macro :").pack(side="left")
        self.hotkey_label = ttk.Label(hot, text="Aucun", style="Strong.TLabel")
        self.hotkey_label.pack(side="left", padx=6)
        self.hotkey_button = ttk.Button(hot, text="Définir…", command=self.set_macro_hotkey)
        self.hotkey_button.pack(side="left")
        tooltip(self.hotkey_button, "Un raccourci global qui lance (ou arrête) directement cette macro.")

        run_bar = ttk.Frame(parent)
        run_bar.pack(fill="x", pady=(10, 6))
        self.record_button = ttk.Button(run_bar, text="●  Enregistrer", command=self.app.toggle_recording)
        self.record_button.pack(side="left")
        self.play_button = ttk.Button(run_bar, text="▶  Lire", style="Accent.TButton",
                                      command=lambda: self.app.play_current())
        self.play_button.pack(side="left", padx=6)
        self.play_from_button = ttk.Button(run_bar, text="▶ Depuis la sélection",
                                           command=self.play_from_selection)
        self.play_from_button.pack(side="left")
        tooltip(self.play_from_button, "Lire à partir de l'action sélectionnée (pratique pour tester).")
        self.stop_button = ttk.Button(run_bar, text="■  Arrêter", command=self.app.stop_all)
        self.stop_button.pack(side="left", padx=6)

        edit_bar = ttk.Frame(parent)
        edit_bar.pack(fill="x", pady=(0, 6))
        self.add_button = ttk.Menubutton(edit_bar, text="+ Ajouter une action", style="Accent.TButton")
        self.add_menu = self._action_menu(self.add_button, self.add_action)
        self.add_button.configure(menu=self.add_menu)
        self.add_button.pack(side="left")
        self.edit_buttons = []
        for text, command, tip in (
            ("Modifier", self.edit_selected, "Modifier l'action (double-clic ou Entrée)"),
            ("Supprimer", self.delete_selected, "Supprimer (Suppr)"),
            ("▲", lambda: self.move_selected(-1), "Monter (Ctrl+↑)"),
            ("▼", lambda: self.move_selected(1), "Descendre (Ctrl+↓)"),
            ("Dupliquer", self.duplicate_selected, "Dupliquer (Ctrl+D)"),
            ("Activer / désactiver", self.toggle_enabled, "Une action désactivée est ignorée à la lecture (Espace)"),
            ("↶", self.undo, "Annuler (Ctrl+Z)"),
            ("↷", self.redo, "Rétablir (Ctrl+Y)"),
        ):
            button = ttk.Button(edit_bar, text=text, command=command, style="Tool.TButton")
            button.pack(side="left", padx=(6 if text in ("Modifier", "▲", "Dupliquer", "↶") else 2, 0))
            tooltip(button, tip)
            self.edit_buttons.append(button)

        table = ttk.Frame(parent)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("n", "action", "details", "delay"), show="headings",
                                 selectmode="extended")
        for column, text, width, anchor, stretch in (
            ("n", "#", 50, "e", False),
            ("action", "Action", 250, "w", False),
            ("details", "Détails", 250, "w", True),
            ("delay", "Délai", 80, "e", False),
        ):
            self.tree.heading(column, text=text, anchor="w" if column in ("action", "details") else "center")
            self.tree.column(column, width=width, minwidth=40, anchor=anchor, stretch=stretch)
        yscroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self._configure_tags()
        self._bind_tree()

        status = ttk.Frame(parent)
        status.pack(fill="x", pady=(6, 4))
        self.info_label = ttk.Label(status, text="", style="Muted.TLabel")
        self.info_label.pack(side="left")
        self.error_label = ttk.Label(status, text="", style="Error.TLabel")
        self.error_label.pack(side="right")

        options = ttk.Frame(parent)
        options.pack(fill="x")
        self._build_play_options(options)
        self._build_record_options(options)

    def _build_play_options(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Lecture de cette macro", padding=(12, 6))
        box.pack(fill="x")
        self.repeat = tk.StringVar(value="1")
        self.speed = tk.StringVar(value="1")
        self.loop_delay = tk.StringVar(value="0")
        self.humanize = tk.StringVar(value="0")
        row = ttk.Frame(box)
        row.pack(fill="x")
        repeat = ttk.Label(row, text="Répétitions")
        repeat.pack(side="left")
        tooltip(repeat, "Nombre d'exécutions de la macro (0 = sans fin, jusqu'à l'arrêt).")
        self.repeat_box = number_entry(row, self.repeat, width=6)
        self.repeat_box.pack(side="left", padx=(6, 4))
        ttk.Label(row, text="(0 = sans fin)", style="Small.TLabel").pack(side="left")
        ttk.Label(row, text="Vitesse").pack(side="left", padx=(18, 0))
        self.speed_box = ttk.Combobox(row, textvariable=self.speed, values=SPEEDS, width=5)
        self.speed_box.pack(side="left", padx=(6, 2))
        ttk.Label(row, text="×").pack(side="left")
        pause = ttk.Label(row, text="Pause")
        pause.pack(side="left", padx=(18, 0))
        tooltip(pause, "Attente entre deux exécutions de la macro.")
        self.loop_delay_box = number_entry(row, self.loop_delay, width=6)
        self.loop_delay_box.pack(side="left", padx=(6, 2))
        ttk.Label(row, text="ms").pack(side="left")
        human = ttk.Label(row, text="Humanisation ±")
        human.pack(side="left", padx=(18, 0))
        tooltip(human, "Fait varier aléatoirement chaque délai de ce pourcentage.")
        self.humanize_box = number_entry(row, self.humanize, width=4)
        self.humanize_box.pack(side="left", padx=(6, 2))
        ttk.Label(row, text="%").pack(side="left")
        for var in (self.repeat, self.speed, self.loop_delay, self.humanize):
            var.trace_add("write", lambda *_a: self._options_changed())

    def _build_record_options(self, parent: ttk.Frame) -> None:
        box = ttk.LabelFrame(parent, text="Enregistrement", padding=(12, 6))
        box.pack(fill="x", pady=(6, 0))
        options = self.app.settings.record
        self.rec_moves = tk.BooleanVar(value=options.record_moves)
        self.rec_delays = tk.BooleanVar(value=options.real_delays)
        self.rec_simplify = tk.BooleanVar(value=options.simplify)
        self.rec_destination = tk.StringVar(value=options.destination)
        row = ttk.Frame(box)
        row.pack(fill="x")
        for text, var, tip in (
            ("Mouvements de souris", self.rec_moves, "Enregistrer aussi les déplacements de la souris."),
            ("Délais réels", self.rec_delays, "Conserver le rythme réel. Sinon, délai fixe "
                                              "(délai par défaut des paramètres)."),
            ("Simplifier", self.rec_simplify, "Regrouper appui + relâchement en clics, "
                                              "doubles clics et appuis de touche."),
        ):
            check = ttk.Checkbutton(row, text=text, variable=var, command=self._record_options_changed)
            check.pack(side="left", padx=(0, 14))
            tooltip(check, tip)
        ttk.Separator(row, orient="vertical").pack(side="left", fill="y", padx=(0, 14))
        ttk.Label(row, text="Vers :").pack(side="left", padx=(0, 6))
        new = ttk.Radiobutton(row, text="une nouvelle macro", value="new", variable=self.rec_destination,
                              command=self._record_options_changed)
        new.pack(side="left")
        append = ttk.Radiobutton(row, text="la fin de celle-ci", value="append",
                                 variable=self.rec_destination, command=self._record_options_changed)
        append.pack(side="left", padx=(10, 0))
        tooltip(append, "Ajoute les actions enregistrées à la fin de la macro ouverte "
                        "(une macro vide est toujours complétée directement).")

    def _action_menu(self, master: tk.Misc, command: Callable[[str], None]) -> tk.Menu:
        menu = tk.Menu(master, tearoff=False)
        for category in CATEGORIES:
            sub = tk.Menu(menu, tearoff=False)
            for spec in ACTION_TYPES.values():
                if spec.category == category:
                    sub.add_command(label=f"{spec.icon}  {spec.label}",
                                    command=lambda t=spec.id: command(t))
            menu.add_cascade(label=category, menu=sub)
        return menu

    def _configure_tags(self) -> None:
        pal = palette()
        self.tree.tag_configure("block", foreground=pal["row_block"])
        self.tree.tag_configure("comment", foreground=pal["row_comment"])
        self.tree.tag_configure("disabled", foreground=pal["row_disabled"])
        self.tree.tag_configure("error", background=pal["row_error"])
        self.tree.tag_configure("current", background=pal["row_current"])

    def refresh_theme(self) -> None:
        self._configure_tags()

    def _bind_tree(self) -> None:
        tree = self.tree
        tree.bind("<Double-1>", self._on_double_click)
        tree.bind("<Return>", lambda _e: self.edit_selected())
        tree.bind("<Delete>", lambda _e: self.delete_selected())
        tree.bind("<space>", lambda _e: self.toggle_enabled())
        tree.bind("<Button-3>", self._on_context_menu)
        tree.bind("<Button-2>", self._on_context_menu)  # macOS
        tree.bind("<<TreeviewSelect>>", lambda _e: self._refresh_buttons())
        for sequence, handler in (
            ("<Control-c>", self.copy_selected), ("<Control-x>", self.cut_selected),
            ("<Control-v>", self.paste), ("<Control-d>", self.duplicate_selected),
            ("<Control-z>", self.undo), ("<Control-y>", self.redo),
            ("<Control-Shift-Z>", self.redo), ("<Control-a>", self.select_all),
            ("<Control-Up>", lambda: self.move_selected(-1)),
            ("<Control-Down>", lambda: self.move_selected(1)),
            ("<Alt-Up>", lambda: self.move_selected(-1)),
            ("<Alt-Down>", lambda: self.move_selected(1)),
        ):
            tree.bind(sequence, lambda _e, h=handler: (h(), "break")[1])

    # ================================================================== bibliothèque

    def refresh_library(self, select: Optional[str] = None) -> None:
        library = self.app.library
        library.refresh()
        hotkeys = library.hotkeys()
        self.lib_tree.delete(*self.lib_tree.get_children())
        for name in library.names():
            shortcut = hotkey_label(hotkeys[name]) if name in hotkeys else ""
            self.lib_tree.insert("", "end", iid=name, values=(name, shortcut))
        names = library.names()
        target = None
        if select and library.exists(select):
            target = next(n for n in names if n.casefold() == select.casefold())
        elif self.macro_name and library.exists(self.macro_name):
            target = self.macro_name
        elif names:
            target = names[0]
        if target is not None:
            self.lib_tree.selection_set(target)
            self.lib_tree.see(target)
            if target != self.macro_name:
                self.open_macro(target)
        else:
            self.open_macro(None)
        for error in library.errors:
            self.app.log.warning("Macro ignorée : %s", error)

    def _on_library_select(self, _event=None) -> None:
        selection = self.lib_tree.selection()
        if selection and selection[0] != self.macro_name:
            self.open_macro(selection[0])

    def open_macro(self, name: Optional[str]) -> None:
        self.flush_save()
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._highlight = None
        if name is None:
            self.macro, self.macro_name = None, None
        else:
            try:
                self.macro = self.app.library.load(name)
                self.macro_name = self.macro.name
            except (KeyError, ValueError, OSError) as exc:
                messagebox.showerror("Macro illisible", f"Impossible d'ouvrir « {name} » :\n{exc}", parent=self)
                self.macro, self.macro_name = None, None
        if self.macro_name:
            self.app.settings.last_macro = self.macro_name
            self.app.save_settings_soon()
        self._load_properties()
        self.refresh_actions()

    def _load_properties(self) -> None:
        self._loading = True
        try:
            macro = self.macro
            self.name_label.configure(text=macro.name if macro else "Aucune macro")
            self.hotkey_label.configure(text=hotkey_label(macro.hotkey) if macro else "—")
            self.repeat.set(str(macro.repeat) if macro else "1")
            self.speed.set(format_number(macro.speed) if macro else "1")
            self.loop_delay.set(str(macro.loop_delay) if macro else "0")
            self.humanize.set(str(macro.humanize) if macro else "0")
        finally:
            self._loading = False

    def _selected_library_name(self) -> Optional[str]:
        selection = self.lib_tree.selection()
        return selection[0] if selection else self.macro_name

    def new_macro(self) -> None:
        name = ask_text(self, "Nouvelle macro", "Nom de la macro :",
                        self.app.library.unique_name("Nouvelle macro"), validate=self._validate_new_name)
        if name is None:
            return
        self.flush_save()
        self.app.library.save(Macro(name))
        self.refresh_library(select=name)
        self.app.update_hotkeys()

    def _validate_new_name(self, value: str) -> str:
        name = validate_name(value)
        if self.app.library.exists(name):
            raise ValueError(f"Une macro nommée « {name} » existe déjà.")
        return name

    def duplicate_macro(self) -> None:
        name = self._selected_library_name()
        if not name:
            return
        self.flush_save()
        macro = self.app.library.load(name)
        macro.name = self.app.library.unique_name(f"{macro.name} (copie)")
        macro.hotkey = ""
        self.app.library.save(macro)
        self.refresh_library(select=macro.name)

    def rename_macro(self) -> None:
        if self.macro is None:
            return
        old = self.macro_name

        def validate(value: str) -> str:
            name = validate_name(value)
            if name.casefold() != (old or "").casefold() and self.app.library.exists(name):
                raise ValueError(f"Une macro nommée « {name} » existe déjà.")
            return name

        name = ask_text(self, "Renommer la macro", "Nouveau nom :", old or "", validate=validate)
        if not name or name == old:
            return
        self._cancel_save_job()
        self.macro.name = name
        try:
            self.app.library.save(self.macro, previous_name=old)
        except (ValueError, OSError) as exc:
            self.macro.name = old
            messagebox.showerror("Renommer", str(exc), parent=self)
            return
        self.macro_name = name
        self._rename_references(old, name)
        self.refresh_library(select=name)
        self.name_label.configure(text=name)
        self.app.update_hotkeys()

    def _rename_references(self, old: str, new: str) -> None:
        """Met à jour les actions « Lancer une macro » qui visaient l'ancien nom."""
        library = self.app.library
        for other in library.names():
            macro = library.get(other)
            if macro is None:
                continue
            changed = False
            for action in macro.actions:
                if action.type == "run_macro" and action.params.get("macro") == old:
                    action.params["macro"] = new
                    changed = True
            if changed:
                library.save(macro, previous_name=macro.name)
                if other == self.macro_name:
                    self.macro = library.load(other)
                    self.refresh_actions()

    def delete_macro(self) -> None:
        name = self._selected_library_name()
        if not name:
            return
        if self.app.settings.confirm_delete and not messagebox.askyesno(
                "Supprimer la macro", f"Supprimer définitivement « {name} » ?", parent=self):
            return
        self._cancel_save_job()
        self.app.library.delete(name)
        if name == self.macro_name:
            self.macro, self.macro_name = None, None
        self.refresh_library()
        self.app.update_hotkeys()

    def import_macro(self) -> None:
        paths = filedialog.askopenfilenames(parent=self, title="Importer des macros",
                                            filetypes=[("Macros Autoclique", "*.json"),
                                                       ("Tous les fichiers", "*")])
        last = None
        for path in paths:
            try:
                macro = self.app.library.import_file(Path(path))
            except (ValueError, OSError) as exc:
                messagebox.showerror("Importer", f"{Path(path).name} :\n{exc}", parent=self)
                continue
            targets = uses_external_program(macro.actions)
            if targets:
                shown = "\n".join(f"• {t}" for t in targets[:8])
                messagebox.showwarning(
                    "Macro importée",
                    f"« {macro.name} » lance des programmes ou des adresses :\n{shown}\n\n"
                    "Vérifiez ces actions avant de lire la macro si vous ne connaissez pas sa source.",
                    parent=self)
            if macro.hotkey:
                macro.hotkey = ""  # évite les conflits : à redéfinir si besoin
                self.app.library.save(macro, previous_name=macro.name)
            last = macro.name
        if last:
            self.refresh_library(select=last)
            self.app.log.info("Macro importée : %s", last)

    def export_macro(self) -> None:
        name = self._selected_library_name()
        if not name:
            return
        self.flush_save()
        path = filedialog.asksaveasfilename(parent=self, title="Exporter la macro",
                                            initialfile=f"{name}.json", defaultextension=".json",
                                            filetypes=[("Macro Autoclique", "*.json")])
        if not path:
            return
        try:
            self.app.library.export(name, Path(path))
        except (KeyError, OSError) as exc:
            messagebox.showerror("Exporter", str(exc), parent=self)
            return
        self.app.set_status(f"Macro exportée : {path}")

    def open_folder(self) -> None:
        from ..core.system import open_folder

        try:
            open_folder(str(self.app.library.folder))
        except Exception as exc:
            messagebox.showerror("Dossier des macros", f"{self.app.library.folder}\n\n{exc}", parent=self)

    def set_macro_hotkey(self) -> None:
        if self.macro is None:
            return
        result = capture_hotkey(self, self.app.hotkeys, current=self.macro.hotkey,
                                title=f"Raccourci de « {self.macro.name} »")
        if result is None:
            return
        if result and not self.app.resolve_hotkey_conflict(result, f"macro:{self.macro_name}"):
            return
        self.macro.hotkey = result
        self.flush_save(force=True)
        self.hotkey_label.configure(text=hotkey_label(result))
        if self.lib_tree.exists(self.macro_name):
            self.lib_tree.set(self.macro_name, "hotkey", hotkey_label(result) if result else "")
        self.app.update_hotkeys()

    def clear_macro_hotkey(self, name: str) -> None:
        """Retire le raccourci d'une macro (appelé en cas de conflit)."""
        if name == self.macro_name and self.macro is not None:
            self.macro.hotkey = ""
            self.flush_save(force=True)
            self.hotkey_label.configure(text="Aucun")
        else:
            macro = self.app.library.get(name)
            if macro is not None:
                macro.hotkey = ""
                self.app.library.save(macro, previous_name=name)
        if self.lib_tree.exists(name):
            self.lib_tree.set(name, "hotkey", "")

    # ================================================================== options

    def _options_changed(self) -> None:
        if self._loading or self.macro is None:
            return
        self.macro.repeat = get_int(self.repeat, 1, 0)
        self.macro.speed = get_float(self.speed, 1.0, 0.05, 100.0)
        self.macro.loop_delay = get_int(self.loop_delay, 0, 0)
        self.macro.humanize = get_int(self.humanize, 0, 0, 90)
        self._refresh_info()
        self._schedule_save()

    def _record_options_changed(self) -> None:
        options = self.app.settings.record
        options.record_moves = bool(self.rec_moves.get())
        options.real_delays = bool(self.rec_delays.get())
        options.simplify = bool(self.rec_simplify.get())
        options.destination = self.rec_destination.get()
        self.app.save_settings_soon()

    def record_options(self) -> RecordOptions:
        self._record_options_changed()
        options = RecordOptions.from_dict(self.app.settings.record.to_dict())
        options.fixed_delay_ms = self.app.settings.default_delay
        return options

    # ================================================================== liste d'actions

    def _row_values(self, index: int, action: Action, depth: int):
        spec = action.spec
        label = spec.label
        if action.type == "loop_start":
            label = "Répéter"
        text = f"{'      ' * depth}{spec.icon}  {label}"
        if not action.enabled:
            text += "  (désactivée)"
        delay = format_ms(action.delay) if (spec.has_delay and action.delay) else ""
        return (index + 1, text, action.describe(), delay)

    def refresh_actions(self, select: Optional[List[int]] = None) -> None:
        tree = self.tree
        tree.delete(*tree.get_children())
        actions = self.macro.actions if self.macro else []
        info = analyze(actions)
        errors = {index for index, _msg in info.errors}
        for index, action in enumerate(actions):
            tags = []
            if action.spec.block:
                tags.append("block")
            if action.type == "comment":
                tags.append("comment")
            if not action.enabled:
                tags.append("disabled")
            if index in errors:
                tags.append("error")
            if index == self._highlight:
                tags.append("current")
            tree.insert("", "end", iid=str(index), values=self._row_values(index, action, info.depth[index]),
                        tags=tags)
        self.error_label.configure(text=f"⚠ {info.error_text(1)}" if info.errors else "")
        if select:
            valid = [str(i) for i in select if 0 <= i < len(actions)]
            if valid:
                tree.selection_set(valid)
                tree.focus(valid[-1])
                tree.see(valid[-1])
        self._refresh_info()
        self._refresh_buttons()

    def _refresh_info(self) -> None:
        if self.macro is None:
            self.info_label.configure(text="Créez une macro (bouton « Nouvelle ») ou enregistrez vos actions.")
            return
        count = len(self.macro.actions)
        if count == 0:
            self.info_label.configure(
                text="Macro vide : ajoutez des actions ou cliquez sur « Enregistrer ».")
            return
        estimate = estimate_duration(self.macro.actions)
        speed = max(0.05, self.macro.speed)
        parts = [f"{count} action{'s' if count > 1 else ''}"]
        if estimate.infinite:
            parts.append("boucle sans fin")
        else:
            one = estimate.seconds / speed
            prefix = "≥ " if estimate.variable else "≈ "
            parts.append(f"{prefix}{format_seconds(one)} par exécution")
            if self.macro.repeat == 0:
                parts.append("répétée sans fin")
            elif self.macro.repeat > 1:
                total = one * self.macro.repeat + self.macro.loop_delay / 1000 / speed * (self.macro.repeat - 1)
                parts.append(f"{prefix}{format_seconds(total)} au total")
        self.info_label.configure(text="   ·   ".join(parts))

    def _refresh_buttons(self) -> None:
        has_macro = self.macro is not None
        selected = bool(self.tree.selection())
        set_enabled([self.add_button, self.hotkey_button, self.play_button, self.repeat_box,
                     self.speed_box, self.loop_delay_box, self.humanize_box], has_macro)
        set_enabled(self.edit_buttons[:6], has_macro and selected)
        set_enabled([self.edit_buttons[6]], bool(self.undo_stack))
        set_enabled([self.edit_buttons[7]], bool(self.redo_stack))
        set_enabled([self.play_from_button], has_macro and selected)
        for text in ("Dupliquer", "Renommer", "Supprimer", "Exporter…"):
            set_enabled([self.library_buttons[text]], has_macro)

    def _selected(self) -> List[int]:
        return sorted(int(i) for i in self.tree.selection())

    def _insert_position(self) -> int:
        selected = self._selected()
        if selected:
            return selected[-1] + 1
        return len(self.macro.actions) if self.macro else 0

    # ================================================================== modifications

    def _snapshot(self) -> list:
        return [a.to_dict() for a in self.macro.actions]

    def _modify(self, change: Callable[[List[Action]], Optional[List[int]]]) -> None:
        if self.macro is None:
            return
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()
        selection = change(self.macro.actions)
        self.refresh_actions(selection)
        self._schedule_save()

    def undo(self) -> None:
        if not self.undo_stack or self.macro is None:
            return
        self.redo_stack.append(self._snapshot())
        self.macro.actions = [Action.from_dict(d) for d in self.undo_stack.pop()]
        self.refresh_actions()
        self._schedule_save()

    def redo(self) -> None:
        if not self.redo_stack or self.macro is None:
            return
        self.undo_stack.append(self._snapshot())
        self.macro.actions = [Action.from_dict(d) for d in self.redo_stack.pop()]
        self.refresh_actions()
        self._schedule_save()

    def add_action(self, type_id: str) -> None:
        if self.macro is None:
            return
        spec = ACTION_TYPES[type_id]
        action = Action.new(type_id, delay=self.app.settings.default_delay if spec.has_delay else 0)
        if any(f.kind != "hidden" for f in spec.fields):
            action = edit_action(self.app, self, action, is_new=True, current_macro_name=self.macro_name)
            if action is None:
                return
        closer = BLOCK_CLOSERS.get(type_id)
        selected = self._selected()

        def change(actions: List[Action]) -> List[int]:
            if closer and selected:
                first, last = selected[0], selected[-1]
                actions.insert(last + 1, Action.new(closer))
                actions.insert(first, action)
                return [first]
            position = selected[-1] + 1 if selected else len(actions)
            actions.insert(position, action)
            if closer:
                actions.insert(position + 1, Action.new(closer))
            return [position]

        self._modify(change)
        self.tree.focus_set()

    def _on_double_click(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            self.edit_selected(int(row))

    def edit_selected(self, index: Optional[int] = None) -> None:
        if self.macro is None:
            return
        if index is None:
            focus = self.tree.focus()
            selected = self._selected()
            if focus and int(focus) in selected:
                index = int(focus)
            elif selected:
                index = selected[0]
            else:
                return
        action = self.macro.actions[index]
        if not any(f.kind != "hidden" for f in action.spec.fields) and not action.spec.has_delay:
            return
        result = edit_action(self.app, self, action, current_macro_name=self.macro_name)
        if result is None:
            return

        def change(actions: List[Action]) -> List[int]:
            actions[index] = result
            return [index]

        self._modify(change)
        self.tree.focus_set()

    def delete_selected(self) -> None:
        selected = self._selected()
        if not selected or self.macro is None:
            return

        def change(actions: List[Action]) -> List[int]:
            for index in reversed(selected):
                del actions[index]
            return [min(selected[0], len(actions) - 1)] if actions else []

        self._modify(change)

    def move_selected(self, delta: int) -> None:
        selected = self._selected()
        if not selected or self.macro is None:
            return
        count = len(self.macro.actions)
        if (delta < 0 and selected[0] == 0) or (delta > 0 and selected[-1] == count - 1):
            return

        def change(actions: List[Action]) -> List[int]:
            order = selected if delta < 0 else list(reversed(selected))
            for index in order:
                actions[index + delta], actions[index] = actions[index], actions[index + delta]
            return [i + delta for i in selected]

        self._modify(change)

    def duplicate_selected(self) -> None:
        selected = self._selected()
        if not selected or self.macro is None:
            return

        def change(actions: List[Action]) -> List[int]:
            copies = [actions[i].copy() for i in selected]
            position = selected[-1] + 1
            actions[position:position] = copies
            return list(range(position, position + len(copies)))

        self._modify(change)

    def toggle_enabled(self) -> None:
        selected = self._selected()
        if not selected or self.macro is None:
            return
        enable = not all(self.macro.actions[i].enabled for i in selected)

        def change(actions: List[Action]) -> List[int]:
            for index in selected:
                actions[index].enabled = enable
            return selected

        self._modify(change)

    def set_delay_selected(self) -> None:
        selected = [i for i in self._selected() if self.macro.actions[i].spec.has_delay]
        if not selected:
            return
        value = ask_number(self, "Délai avant l'action",
                           f"Nouveau délai pour {len(selected)} action(s) :",
                           self.macro.actions[selected[0]].delay, 0, 86_400_000, "ms")
        if value is None:
            return

        def change(actions: List[Action]) -> List[int]:
            for index in selected:
                actions[index].delay = int(value)
            return selected

        self._modify(change)

    def select_all(self) -> None:
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children)

    def copy_selected(self) -> None:
        if self.macro is None:
            return
        selected = self._selected()
        if selected:
            self.app.clipboard = [self.macro.actions[i].copy() for i in selected]
            self.app.set_status(f"{len(selected)} action(s) copiée(s).")

    def cut_selected(self) -> None:
        self.copy_selected()
        self.delete_selected()

    def paste(self) -> None:
        if self.macro is None or not self.app.clipboard:
            return
        copies = [a.copy() for a in self.app.clipboard]
        position = self._insert_position()

        def change(actions: List[Action]) -> List[int]:
            actions[position:position] = copies
            return list(range(position, position + len(copies)))

        self._modify(change)

    def play_from_selection(self) -> None:
        selected = self._selected()
        if selected:
            self.app.play_current(start_index=selected[0])

    def _on_context_menu(self, event) -> None:
        if self.macro is None:
            return
        row = self.tree.identify_row(event.y)
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
            self.tree.focus(row)
        has = bool(self.tree.selection())
        menu = tk.Menu(self, tearoff=False)
        state = "normal" if has else "disabled"
        menu.add_command(label="Modifier…", command=self.edit_selected, state=state)
        menu.add_command(label="Modifier le délai…", command=self.set_delay_selected, state=state)
        menu.add_cascade(label="Insérer après", menu=self._action_menu(menu, self.add_action))
        menu.add_separator()
        menu.add_command(label="Couper", accelerator="Ctrl+X", command=self.cut_selected, state=state)
        menu.add_command(label="Copier", accelerator="Ctrl+C", command=self.copy_selected, state=state)
        menu.add_command(label="Coller", accelerator="Ctrl+V", command=self.paste,
                         state="normal" if self.app.clipboard else "disabled")
        menu.add_command(label="Dupliquer", accelerator="Ctrl+D", command=self.duplicate_selected, state=state)
        menu.add_command(label="Supprimer", accelerator="Suppr", command=self.delete_selected, state=state)
        menu.add_separator()
        menu.add_command(label="Activer / désactiver", accelerator="Espace", command=self.toggle_enabled,
                         state=state)
        menu.add_command(label="Lire à partir d'ici", command=self.play_from_selection, state=state)
        menu.add_separator()
        menu.add_command(label="Tout sélectionner", accelerator="Ctrl+A", command=self.select_all)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    # ================================================================== enregistrement / lecture

    def receive_recording(self, actions: List[Action], options: RecordOptions) -> None:
        if not actions:
            return
        if self.macro is not None and (not self.macro.actions or options.destination == "append"):
            added = [a.copy() for a in actions]

            def change(current: List[Action]) -> List[int]:
                start = len(current)
                current.extend(added)
                return list(range(start, len(current)))

            self._modify(change)
            self.flush_save()
            return
        self.flush_save()
        name = self.app.library.unique_name(time.strftime("Enregistrement du %d-%m à %Hh%M"))
        self.app.library.save(Macro(name, [a.copy() for a in actions]))
        self.refresh_library(select=name)

    def macro_for_playback(self) -> Optional[Macro]:
        if self.macro is None:
            return None
        self.flush_save()
        return self.macro.copy()

    def highlight(self, index: Optional[int]) -> None:
        if index == self._highlight:
            return
        tree = self.tree
        previous = self._highlight
        self._highlight = index
        for item, add in ((previous, False), (index, True)):
            if item is None or not tree.exists(str(item)):
                continue
            tags = list(tree.item(str(item), "tags"))
            if add and "current" not in tags:
                tags.append("current")
            elif not add and "current" in tags:
                tags.remove("current")
            tree.item(str(item), tags=tags)
        if index is not None and tree.exists(str(index)):
            tree.see(str(index))

    def show_step(self, index: int) -> None:
        if self.tree.exists(str(index)):
            self.tree.selection_set(str(index))
            self.tree.focus(str(index))
            self.tree.see(str(index))

    def _shortcut(self, binding: str) -> str:
        label = hotkey_label(self.app.settings.hotkeys.get(binding, ""))
        return f" ({label})" if label != "Aucun" else ""

    def set_running(self, kind: Optional[str]) -> None:
        self._running = kind
        recording = kind == "record"
        busy = kind is not None
        if recording:
            self.record_button.configure(text=f"■  Arrêter l'enregistrement{self._shortcut('record')}")
        else:
            self.record_button.configure(text=f"●  Enregistrer{self._shortcut('record')}")
        set_enabled([self.record_button], recording or not busy)
        set_enabled([self.play_button, self.play_from_button], not busy and self.macro is not None)
        set_enabled([self.stop_button], busy and not recording)
        if not busy:
            self._refresh_buttons()

    def refresh_hotkeys(self) -> None:
        self.play_button.configure(text=f"▶  Lire{self._shortcut('play')}")
        self.set_running(getattr(self, "_running", None))

    # ================================================================== sauvegarde

    def _schedule_save(self) -> None:
        self._cancel_save_job()
        self._save_job = self.after(400, self.flush_save)

    def _cancel_save_job(self) -> None:
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except tk.TclError:
                pass
            self._save_job = None

    def flush_save(self, force: bool = False) -> None:
        """Enregistre immédiatement la macro ouverte si une sauvegarde est en attente."""
        pending = self._save_job is not None
        self._cancel_save_job()
        if self.macro is None or not (pending or force):
            return
        try:
            self.app.library.save(self.macro, previous_name=self.macro_name)
            self.macro_name = self.macro.name
        except (ValueError, OSError) as exc:
            self.app.log.error("Enregistrement de la macro impossible : %s", exc)
            messagebox.showerror("Enregistrement impossible", str(exc), parent=self)
