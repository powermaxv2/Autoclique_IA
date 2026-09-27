"""Thème visuel : Sun Valley (sv-ttk) clair ou sombre, sinon thème Tk natif."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Dict

PALETTES: Dict[str, Dict[str, str]] = {
    "dark": {
        "bg": "#1c1c1c", "fg": "#fafafa", "field": "#2b2b2b", "border": "#3a3a3a",
        "muted": "#a0a0a0", "accent": "#57c8ff", "select": "#2f60d8",
        "ok": "#6ccb5f", "warn": "#fce100", "error": "#ff99a4",
        "recording": "#ff6b6b", "playing": "#57c8ff", "idle": "#8a8a8a",
        "row_current": "#1f4a6e", "row_error": "#5c2b2f", "row_disabled": "#6f6f6f",
        "row_comment": "#8fbf8f", "row_block": "#c8a2ff", "overlay": "#000000",
    },
    "light": {
        "bg": "#fafafa", "fg": "#1c1c1c", "field": "#ffffff", "border": "#d0d0d0",
        "muted": "#5f5f5f", "accent": "#005fb8", "select": "#2f60d8",
        "ok": "#0f7b0f", "warn": "#9d5d00", "error": "#c42b1c",
        "recording": "#c42b1c", "playing": "#005fb8", "idle": "#8a8a8a",
        "row_current": "#cce4f7", "row_error": "#fde7e9", "row_disabled": "#a0a0a0",
        "row_comment": "#2e7d32", "row_block": "#6a1b9a", "overlay": "#000000",
    },
}

_state = {"name": "dark", "sv_ttk": False}


def palette() -> Dict[str, str]:
    return PALETTES[_state["name"]]


def current_theme() -> str:
    return _state["name"]


def _base_font(root: tk.Misc) -> tkfont.Font:
    for name in ("SunValleyBodyFont", "TkDefaultFont"):
        try:
            return tkfont.nametofont(name, root=root)
        except (tk.TclError, TypeError):
            try:
                return tkfont.nametofont(name)
            except tk.TclError:
                continue
    return tkfont.Font(root=root)


def _named_font(root: tk.Misc, name: str, **options) -> None:
    try:
        font = tkfont.nametofont(name, root=root)
    except (tk.TclError, TypeError):
        font = tkfont.Font(root=root, name=name, exists=False)
    font.configure(**options)


def apply_theme(root: tk.Tk, name: str) -> Dict[str, str]:
    """Applique le thème ``"dark"`` ou ``"light"`` et renvoie sa palette."""
    name = name if name in PALETTES else "dark"
    _state["name"] = name
    try:
        import sv_ttk

        try:
            sv_ttk.set_theme(name, root)
        except TypeError:  # anciennes versions : set_theme(theme)
            sv_ttk.set_theme(name)
        _state["sv_ttk"] = True
    except Exception:
        _state["sv_ttk"] = False
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
    pal = PALETTES[name]
    style = ttk.Style(root)
    base = _base_font(root)
    family = base.actual("family")
    size = abs(int(base.actual("size"))) or 10
    _named_font(root, "AppBody", family=family, size=size)
    _named_font(root, "AppTitle", family=family, size=size + 7, weight="bold")
    _named_font(root, "AppSubtitle", family=family, size=size + 2, weight="bold")
    _named_font(root, "AppStrong", family=family, size=size, weight="bold")
    _named_font(root, "AppSmall", family=family, size=max(8, size - 1))
    _named_font(root, "AppBig", family=family, size=size + 2, weight="bold")
    _named_font(root, "AppMono", family=tkfont.nametofont("TkFixedFont").actual("family"), size=size)

    if not _state["sv_ttk"]:
        style.configure(".", background=pal["bg"], foreground=pal["fg"], fieldbackground=pal["field"])
        style.configure("TLabelframe", background=pal["bg"])
        style.configure("TLabelframe.Label", background=pal["bg"], foreground=pal["fg"])
        style.configure("Treeview", background=pal["field"], fieldbackground=pal["field"],
                        foreground=pal["fg"])
        style.map("Treeview", background=[("selected", pal["select"])],
                  foreground=[("selected", "#ffffff")])
        style.configure("Accent.TButton", foreground=pal["accent"])
    style.configure("Title.TLabel", font="AppTitle")
    style.configure("Subtitle.TLabel", font="AppSubtitle")
    style.configure("Strong.TLabel", font="AppStrong")
    style.configure("Muted.TLabel", foreground=pal["muted"])
    style.configure("Small.TLabel", foreground=pal["muted"], font="AppSmall")
    style.configure("Error.TLabel", foreground=pal["error"])
    style.configure("Ok.TLabel", foreground=pal["ok"])
    style.configure("Big.Accent.TButton", font="AppBig", padding=(18, 8))
    style.configure("Big.TButton", font="AppBig", padding=(18, 8))
    style.configure("Tool.TButton", padding=(6, 2))
    style.configure("Status.TFrame", background=pal["bg"])
    root.configure(background=pal["bg"])
    root.option_add("*TCombobox*Listbox.background", pal["field"])
    root.option_add("*TCombobox*Listbox.foreground", pal["fg"])
    return pal


def style_text_widget(widget: tk.Text) -> None:
    """Couleurs d'un widget Tk classique (Text, Listbox, Canvas)."""
    pal = palette()
    options = {"background": pal["field"], "foreground": pal["fg"], "highlightthickness": 1,
               "highlightbackground": pal["border"], "highlightcolor": pal["accent"],
               "relief": "flat", "borderwidth": 0}
    if isinstance(widget, (tk.Text, tk.Entry)):
        options["insertbackground"] = pal["fg"]
    if isinstance(widget, (tk.Text, tk.Listbox, tk.Entry)):
        options["selectbackground"] = pal["select"]
        options["selectforeground"] = "#ffffff"
    if isinstance(widget, tk.Canvas):
        options = {"background": pal["field"], "highlightthickness": 0}
    for key, value in options.items():
        try:
            widget.configure(**{key: value})
        except tk.TclError:
            pass
