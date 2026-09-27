"""Boîtes de dialogue : capture de raccourci, saisie de texte ou de nombre."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from ..core.keys import KeyRef, hotkey_label, key_label, parse_hotkey
from .widgets import center_on, get_float, number_box


class _Modal(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.resizable(False, False)
        try:
            self.transient(parent.winfo_toplevel())
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.bind("<Escape>", lambda _e: self.cancel())
        self.result = None

    def show(self):
        center_on(self, self.master)
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_force()
        self.wait_window(self)
        return self.result

    def cancel(self) -> None:
        self.result = None
        self.destroy()


class CaptureDialog(_Modal):
    """Attend l'appui d'un raccourci (``mode="combo"``) ou d'une touche
    (``mode="key"``) grâce aux écouteurs globaux.

    Résultat : ``None`` si annulé, ``""`` si « Aucun » est choisi, sinon la
    chaîne du raccourci (mode combo) ou un :class:`KeyRef` (mode key).
    """

    def __init__(self, parent: tk.Misc, hotkeys, mode: str = "combo", title: str = "",
                 current: str = "", allow_clear: bool = True) -> None:
        super().__init__(parent, title or ("Choisir un raccourci" if mode == "combo" else "Choisir une touche"))
        self.hotkeys = hotkeys
        self.mode = mode
        self._queue: "queue.Queue[object]" = queue.Queue()
        body = ttk.Frame(self, padding=20)
        body.pack(fill="both", expand=True)
        if mode == "combo":
            prompt = "Appuyez sur la touche ou la combinaison souhaitée\n(par exemple F6 ou Ctrl+Maj+A)."
        else:
            prompt = "Appuyez sur la touche souhaitée."
        ttk.Label(body, text=prompt, style="Subtitle.TLabel", justify="center").pack(pady=(0, 10))
        if mode == "combo":
            ttk.Label(body, text="Les boutons latéraux et le clic milieu de la souris sont acceptés.",
                      style="Muted.TLabel").pack()
        if current:
            ttk.Label(body, text=f"Actuel : {hotkey_label(current) if mode == 'combo' else key_label(current)}",
                      style="Muted.TLabel").pack(pady=(6, 0))
        self.manual = tk.StringVar(value=hotkey_label(current) if (current and mode == "combo") else current)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(16, 0))
        if hotkeys is None:
            ttk.Label(body, text="Détection des touches indisponible : saisissez-la.",
                      style="Error.TLabel").pack(pady=(8, 4))
            entry = ttk.Entry(body, textvariable=self.manual, width=28)
            entry.pack()
            entry.focus_set()
            ttk.Button(buttons, text="Valider", style="Accent.TButton", command=self._manual_ok).pack(side="right")
        else:
            hotkeys.begin_capture(self._queue.put, mode)
            self.after(50, self._poll)
        ttk.Button(buttons, text="Annuler", command=self.cancel).pack(side="right", padx=(0, 6))
        if allow_clear:
            ttk.Button(buttons, text="Aucun", command=self._clear).pack(side="left")

    def _poll(self) -> None:
        try:
            value = self._queue.get_nowait()
        except queue.Empty:
            if self.winfo_exists():
                self.after(50, self._poll)
            return
        if self.mode == "combo" and not self._confirm_plain(str(value)):
            self.hotkeys.begin_capture(self._queue.put, self.mode)
            self.after(50, self._poll)
            return
        self.result = value
        self.destroy()

    def _confirm_plain(self, combo: str) -> bool:
        try:
            hotkey = parse_hotkey(combo)
        except ValueError:
            return False
        typing_key = len(hotkey.key) == 1 or hotkey.key == "space"
        if hotkey.mods or hotkey.is_mouse or not typing_key:
            return True
        return messagebox.askyesno(
            "Raccourci sans modificateur",
            f"La touche « {hotkey.label()} » seule sera détectée partout, même pendant que vous "
            "écrivez du texte.\n\nL'utiliser quand même ?",
            parent=self,
        )

    def _manual_ok(self) -> None:
        text = self.manual.get().strip()
        try:
            if self.mode == "combo":
                self.result = str(parse_hotkey(text))
            else:
                from ..core.keys import normalize_key

                self.result = KeyRef(normalize_key(text))
        except ValueError as exc:
            messagebox.showerror("Saisie invalide", str(exc), parent=self)
            return
        self.destroy()

    def _clear(self) -> None:
        self.result = ""
        self.destroy()

    def destroy(self) -> None:
        if self.hotkeys is not None:
            self.hotkeys.cancel_capture()
        super().destroy()


class TextDialog(_Modal):
    def __init__(self, parent: tk.Misc, title: str, prompt: str, initial: str = "",
                 validate=None) -> None:
        super().__init__(parent, title)
        self.validate = validate
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=prompt).pack(anchor="w", pady=(0, 6))
        self.var = tk.StringVar(value=initial)
        entry = ttk.Entry(body, textvariable=self.var, width=42)
        entry.pack(fill="x")
        entry.select_range(0, "end")
        entry.focus_set()
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="OK", style="Accent.TButton", command=self._ok).pack(side="right")
        ttk.Button(buttons, text="Annuler", command=self.cancel).pack(side="right", padx=(0, 6))
        self.bind("<Return>", lambda _e: self._ok())

    def _ok(self) -> None:
        value = self.var.get()
        if self.validate is not None:
            try:
                value = self.validate(value)
            except ValueError as exc:
                messagebox.showerror(self.title(), str(exc), parent=self)
                return
        self.result = value
        self.destroy()


class NumberDialog(_Modal):
    def __init__(self, parent: tk.Misc, title: str, prompt: str, initial: float,
                 minimum: float, maximum: float, unit: str = "", is_float: bool = False) -> None:
        super().__init__(parent, title)
        self.minimum, self.maximum, self.is_float = minimum, maximum, is_float
        body = ttk.Frame(self, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=prompt).pack(anchor="w", pady=(0, 6))
        row = ttk.Frame(body)
        row.pack(anchor="w")
        self.var = tk.StringVar(value=str(initial))
        box = number_box(row, self.var, minimum, maximum, width=10, is_float=is_float)
        box.pack(side="left")
        if unit:
            ttk.Label(row, text=unit).pack(side="left", padx=(6, 0))
        box.focus_set()
        box.selection_range(0, "end")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="OK", style="Accent.TButton", command=self._ok).pack(side="right")
        ttk.Button(buttons, text="Annuler", command=self.cancel).pack(side="right", padx=(0, 6))
        self.bind("<Return>", lambda _e: self._ok())

    def _ok(self) -> None:
        value = get_float(self.var, self.minimum, self.minimum, self.maximum)
        self.result = value if self.is_float else int(round(value))
        self.destroy()


def capture_hotkey(parent: tk.Misc, hotkeys, current: str = "", allow_clear: bool = True,
                   title: str = "") -> Optional[str]:
    return CaptureDialog(parent, hotkeys, "combo", title, current, allow_clear).show()


def capture_key(parent: tk.Misc, hotkeys, current: str = "") -> Optional[KeyRef]:
    result = CaptureDialog(parent, hotkeys, "key", "", current, allow_clear=False).show()
    return result if isinstance(result, KeyRef) else None


def ask_text(parent: tk.Misc, title: str, prompt: str, initial: str = "", validate=None) -> Optional[str]:
    return TextDialog(parent, title, prompt, initial, validate).show()


def ask_number(parent: tk.Misc, title: str, prompt: str, initial: float, minimum: float,
               maximum: float, unit: str = "", is_float: bool = False):
    return NumberDialog(parent, title, prompt, initial, minimum, maximum, unit, is_float).show()
