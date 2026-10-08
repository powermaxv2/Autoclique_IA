"""Petits composants réutilisables de l'interface."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Iterable, Optional

from .theme import palette


class Tooltip:
    """Bulle d'aide affichée au survol d'un widget."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 600) -> None:
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self) -> None:
        if not self.text or self._tip is not None:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        pal = palette()
        tip = tk.Toplevel(self.widget)
        tip.wm_overrideredirect(True)
        tip.attributes("-topmost", True)
        label = tk.Label(tip, text=self.text, justify="left", background=pal["field"],
                         foreground=pal["fg"], relief="solid", borderwidth=1,
                         wraplength=360, padx=8, pady=5)
        label.pack()
        tip.wm_geometry(f"+{x}+{y}")
        self._tip = tip

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None


def tooltip(widget: tk.Widget, text: str) -> tk.Widget:
    Tooltip(widget, text)
    return widget


def _validate_number(text: str, allow_float: str, allow_negative: str) -> bool:
    if text in ("", "-") and allow_negative == "1":
        return True
    if text == "":
        return True
    body = text[1:] if (allow_negative == "1" and text.startswith("-")) else text
    if allow_float == "1":
        body = body.replace(",", ".", 1)
        if body.count(".") > 1:
            return False
        return body.replace(".", "", 1).isdigit() or body == "."
    return body.isdigit()


def number_box(parent: tk.Widget, variable: tk.StringVar, minimum: float, maximum: float,
               width: int = 7, increment: float = 1, is_float: bool = False) -> ttk.Spinbox:
    """Champ numérique avec flèches, qui refuse les saisies non numériques."""
    box = ttk.Spinbox(parent, textvariable=variable, from_=minimum, to=maximum,
                      increment=increment, width=width)
    command = (parent.register(_validate_number), "%P", "1" if is_float else "0",
               "1" if minimum < 0 else "0")
    box.configure(validate="key", validatecommand=command)
    return box


def number_entry(parent: tk.Widget, variable: tk.StringVar, width: int = 5,
                 is_float: bool = False, negative: bool = False) -> ttk.Entry:
    """Champ numérique compact (sans flèches)."""
    entry = ttk.Entry(parent, textvariable=variable, width=width, justify="right")
    command = (parent.register(_validate_number), "%P", "1" if is_float else "0", "1" if negative else "0")
    entry.configure(validate="key", validatecommand=command)
    return entry


def get_int(variable: tk.Variable, default: int = 0, minimum: Optional[int] = None,
            maximum: Optional[int] = None) -> int:
    try:
        value = int(round(float(str(variable.get()).replace(",", ".").strip())))
    except (ValueError, tk.TclError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def get_float(variable: tk.Variable, default: float = 0.0, minimum: Optional[float] = None,
              maximum: Optional[float] = None) -> float:
    try:
        value = float(str(variable.get()).replace(",", ".").strip())
    except (ValueError, tk.TclError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def format_number(value: float) -> str:
    """1.5 -> « 1,5 » ; 2.0 -> « 2 »."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.3f}".rstrip("0").rstrip(".").replace(".", ",")


def set_enabled(widgets: Iterable[tk.Widget], enabled: bool) -> None:
    for widget in widgets:
        try:
            if isinstance(widget, ttk.Widget):
                widget.state(["!disabled"] if enabled else ["disabled"])
                if isinstance(widget, ttk.Combobox) and enabled and getattr(widget, "_readonly", False):
                    widget.state(["readonly"])
            else:
                widget.configure(state="normal" if enabled else "disabled")
        except tk.TclError:
            pass


def readonly_combobox(parent: tk.Widget, variable: tk.StringVar, values, width: int = 18) -> ttk.Combobox:
    box = ttk.Combobox(parent, textvariable=variable, values=list(values), width=width, state="readonly")
    box._readonly = True  # type: ignore[attr-defined]
    return box


def center_on(window: tk.Toplevel, parent: tk.Misc) -> None:
    """Centre ``window`` sur ``parent`` (ou sur l'écran si le parent est caché)."""
    window.update_idletasks()
    width, height = window.winfo_reqwidth(), window.winfo_reqheight()
    try:
        if parent.winfo_viewable():
            px, py = parent.winfo_rootx(), parent.winfo_rooty()
            pw, ph = parent.winfo_width(), parent.winfo_height()
        else:
            raise tk.TclError
    except tk.TclError:
        px, py = 0, 0
        pw, ph = window.winfo_screenwidth(), window.winfo_screenheight()
    x = max(0, px + (pw - width) // 2)
    y = max(0, py + (ph - height) // 3)
    window.geometry(f"+{x}+{y}")


class ScrollableFrame(ttk.Frame):
    """Cadre avec barre de défilement verticale (formulaires longs)."""

    def __init__(self, parent: tk.Widget, max_height: int = 520, **kwargs) -> None:
        super().__init__(parent, **kwargs)
        self.max_height = max_height
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0,
                                background=palette()["bg"])
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.inner.bind("<Enter>", lambda _e: self._bind_wheel(True))
        self.inner.bind("<Leave>", lambda _e: self._bind_wheel(False))

    def _on_inner(self, _event=None) -> None:
        width = self.inner.winfo_reqwidth()
        height = self.inner.winfo_reqheight()
        self.canvas.configure(scrollregion=(0, 0, width, height), width=width,
                              height=min(height, self.max_height))
        if height > self.max_height:
            self.scrollbar.grid(row=0, column=1, sticky="ns")
        else:
            self.scrollbar.grid_remove()

    def _on_canvas(self, event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, active: bool) -> None:
        if active:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
            self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-2, "units"))
            self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(2, "units"))
        else:
            self.canvas.unbind_all("<MouseWheel>")
            self.canvas.unbind_all("<Button-4>")
            self.canvas.unbind_all("<Button-5>")

    def _on_wheel(self, event) -> None:
        if self.inner.winfo_reqheight() > self.max_height:
            self.canvas.yview_scroll(int(-event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
