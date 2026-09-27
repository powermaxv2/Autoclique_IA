"""Fenêtre de création / modification d'une action de macro.

Le formulaire est construit automatiquement à partir du schéma de l'action
(:mod:`autoclique.core.actions`) : chaque type de champ a son éditeur.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk
from typing import Any, Dict, Optional

from ..core.actions import Action, FieldSpec, image_size, normalize_color, rgb_to_color
from ..core.keys import NUMPAD_KEYS, PLATFORM, SPECIAL_KEYS, key_label, normalize_key, parse_hotkey
from .dialogs import capture_hotkey, capture_key
from .theme import palette, style_text_widget
from .widgets import center_on, format_number, number_box, readonly_combobox, set_enabled, tooltip

COMMON_KEYS = [
    "enter", "space", "esc", "tab", "backspace", "delete", "up", "down", "left", "right",
    "shift", "ctrl", "alt", "cmd", "home", "end", "page_up", "page_down", "insert",
] + [f"f{i}" for i in range(1, 13)] + list(NUMPAD_KEYS) + [
    "caps_lock", "num_lock", "print_screen", "pause", "menu", "media_play_pause",
    "media_next", "media_previous", "media_volume_up", "media_volume_down", "media_volume_mute",
]

IMAGE_TYPES = ("click_image", "wait_image", "if_image")
PIXEL_TYPES = ("wait_pixel", "if_pixel")


def editable_key_text(name: str) -> str:
    """Texte affiché pour une touche, relisible par ``normalize_key``."""
    if not name:
        return ""
    if name.startswith("vk:"):
        return name
    return key_label(name)


class FieldEditor:
    full_row = False  # l'éditeur porte lui-même son libellé

    def __init__(self, dialog: "ActionDialog", parent: tk.Widget, spec: FieldSpec, value: Any) -> None:
        self.dialog = dialog
        self.spec = spec
        self.frame = ttk.Frame(parent)

    def get(self) -> Any:
        raise NotImplementedError

    def focus(self) -> None:
        pass

    def _error(self, message: str) -> ValueError:
        return ValueError(f"{self.spec.label} : {message}")


class NumberEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value, is_float=False):
        super().__init__(dialog, parent, spec, value)
        self.is_float = is_float
        self.var = tk.StringVar(value=format_number(value if value is not None else spec.default))
        minimum = spec.minimum if spec.minimum is not None else -1e9
        maximum = spec.maximum if spec.maximum is not None else 1e9
        increment = 0.5 if is_float else (10 if spec.unit == "ms" else 1)
        self.box = number_box(self.frame, self.var, minimum, maximum, width=10,
                              increment=increment, is_float=is_float)
        self.box.pack(side="left")
        if spec.unit:
            ttk.Label(self.frame, text=spec.unit).pack(side="left", padx=(6, 0))

    def get(self):
        text = self.var.get().strip().replace(",", ".")
        if text in ("", "-", "."):
            raise self._error("valeur manquante.")
        try:
            value = float(text)
        except ValueError:
            raise self._error("nombre invalide.") from None
        if not self.is_float:
            value = int(round(value))
        lo, hi = self.spec.minimum, self.spec.maximum
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            raise self._error(f"doit être compris entre {format_number(lo)} et {format_number(hi)}.")
        return value

    def focus(self):
        self.box.focus_set()


class BoolEditor(FieldEditor):
    full_row = True

    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.var = tk.BooleanVar(value=bool(value))
        ttk.Checkbutton(self.frame, text=spec.label, variable=self.var).pack(side="left")

    def get(self):
        return bool(self.var.get())


class ChoiceEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.values = [choice for choice, _label in spec.choices]
        self.labels = [label for _choice, label in spec.choices]
        index = self.values.index(value) if value in self.values else 0
        self.var = tk.StringVar(value=self.labels[index])
        self.box = readonly_combobox(self.frame, self.var, self.labels, width=24)
        self.box.pack(side="left")

    def get(self):
        return self.values[self.labels.index(self.var.get())]


class TextEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.var = tk.StringVar(value=value or "")
        self.entry = ttk.Entry(self.frame, textvariable=self.var, width=46)
        self.entry.pack(side="left", fill="x", expand=True)

    def get(self):
        return self.var.get()

    def focus(self):
        self.entry.focus_set()


class TargetEditor(TextEditor):
    """Programme / fichier / URL, avec un bouton « Parcourir »."""

    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.entry.configure(width=38)
        ttk.Button(self.frame, text="Parcourir…", command=self._browse).pack(side="left", padx=(6, 0))

    def _browse(self):
        path = filedialog.askopenfilename(parent=self.dialog, title="Choisir un programme ou un fichier")
        if path:
            self.var.set(path)

    def get(self):
        value = self.var.get().strip()
        if not value:
            raise self._error("indiquez un programme, un fichier ou une adresse web.")
        return value


class MultilineEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.text = tk.Text(self.frame, width=46, height=6, wrap="word", undo=True, font="AppBody")
        style_text_widget(self.text)
        self.text.insert("1.0", value or "")
        self.text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.text.yview)
        scroll.pack(side="left", fill="y")
        self.text.configure(yscrollcommand=scroll.set)

    def get(self):
        return self.text.get("1.0", "end-1c")

    def focus(self):
        self.text.focus_set()


class KeyEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value, vk=None, vk_os=None):
        super().__init__(dialog, parent, spec, value)
        self.vk, self.vk_os = vk, vk_os
        self._setting = False
        self.var = tk.StringVar(value=editable_key_text(value or ""))
        self.box = ttk.Combobox(self.frame, textvariable=self.var, width=22,
                                values=[key_label(k) for k in COMMON_KEYS])
        self.box.pack(side="left")
        button = ttk.Button(self.frame, text="Capturer…", command=self._capture)
        button.pack(side="left", padx=(6, 0))
        tooltip(button, "Appuyez sur la touche à reproduire.")
        self.var.trace_add("write", self._typed)

    def _typed(self, *_args):
        if not self._setting:
            self.vk, self.vk_os = None, None

    def _capture(self):
        ref = capture_key(self.dialog, self.dialog.app.hotkeys, "")
        if ref is None:
            return
        self._setting = True
        self.var.set(editable_key_text(ref.name))
        self._setting = False
        self.vk = ref.vk
        self.vk_os = PLATFORM if ref.vk is not None else None

    def get(self):
        try:
            return normalize_key(self.var.get())
        except ValueError as exc:
            raise self._error(str(exc)) from None

    def focus(self):
        self.box.focus_set()


class ComboEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        try:
            text = parse_hotkey(value).label() if value else ""
        except ValueError:
            text = value or ""
        self.var = tk.StringVar(value=text)
        self.entry = ttk.Entry(self.frame, textvariable=self.var, width=24)
        self.entry.pack(side="left")
        ttk.Button(self.frame, text="Capturer…", command=self._capture).pack(side="left", padx=(6, 0))

    def _capture(self):
        result = capture_hotkey(self.dialog, self.dialog.app.hotkeys, allow_clear=False,
                                title="Combinaison à envoyer")
        if result:
            self.var.set(parse_hotkey(result).label())

    def get(self):
        try:
            hotkey = parse_hotkey(self.var.get())
        except ValueError as exc:
            raise self._error(str(exc)) from None
        if hotkey.is_mouse:
            raise self._error("une combinaison ne peut pas contenir de bouton de souris.")
        return str(hotkey)

    def focus(self):
        self.entry.focus_set()


class ColorEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.var = tk.StringVar(value=value or "#FFFFFF")
        self.entry = ttk.Entry(self.frame, textvariable=self.var, width=10)
        self.entry.pack(side="left")
        self.swatch = tk.Frame(self.frame, width=26, height=22, highlightthickness=1,
                               highlightbackground=palette()["border"])
        self.swatch.pack(side="left", padx=6)
        ttk.Button(self.frame, text="Palette…", command=self._choose).pack(side="left")
        self.var.trace_add("write", lambda *_a: self._refresh())
        self._refresh()

    def _refresh(self):
        try:
            self.swatch.configure(background=normalize_color(self.var.get()))
        except (ValueError, tk.TclError):
            pass

    def _choose(self):
        try:
            initial = normalize_color(self.var.get())
        except ValueError:
            initial = "#FFFFFF"
        chosen = colorchooser.askcolor(color=initial, parent=self.dialog, title="Couleur")
        if chosen and chosen[1]:
            self.var.set(chosen[1].upper())

    def set_rgb(self, rgb):
        self.var.set(rgb_to_color(rgb))

    def get(self):
        try:
            return normalize_color(self.var.get())
        except ValueError as exc:
            raise self._error(str(exc)) from None


class PointEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        x, y = value if value is not None else (0, 0)
        self.current = tk.BooleanVar(value=value is None)
        self.x = tk.StringVar(value=str(x))
        self.y = tk.StringVar(value=str(y))
        row = ttk.Frame(self.frame)
        row.pack(anchor="w")
        if spec.optional:
            ttk.Checkbutton(self.frame, text="Position actuelle du curseur", variable=self.current,
                            command=self._toggle).pack(anchor="w", before=row, pady=(0, 4))
        ttk.Label(row, text="X").pack(side="left")
        self.xbox = number_box(row, self.x, -100000, 100000, width=7)
        self.xbox.pack(side="left", padx=(4, 10))
        ttk.Label(row, text="Y").pack(side="left")
        self.ybox = number_box(row, self.y, -100000, 100000, width=7)
        self.ybox.pack(side="left", padx=(4, 10))
        self.pick = ttk.Button(row, text="Choisir à l'écran…", command=self._pick)
        self.pick.pack(side="left")
        self.show = ttk.Button(row, text="Montrer", command=self._show)
        self.show.pack(side="left", padx=(6, 0))
        tooltip(self.show, "Encadre brièvement ce point à l'écran.")
        self._toggle()

    def _toggle(self):
        set_enabled([self.xbox, self.ybox, self.pick, self.show],
                    not (self.spec.optional and self.current.get()))

    def _pick(self):
        def done(result):
            if result is None:
                return
            x, y, rgb = result
            self.current.set(False)
            self.x.set(str(x))
            self.y.set(str(y))
            self._toggle()
            color_editor = self.dialog.editors.get("color")
            if isinstance(color_editor, ColorEditor):
                color_editor.set_rgb(rgb)

        self.dialog.app.pick_point(done, parent=self.dialog)

    def _show(self):
        try:
            x, y = self.get() or (0, 0)
        except ValueError:
            return
        self.dialog.app.flash_point(x, y)

    def get(self):
        if self.spec.optional and self.current.get():
            return None
        try:
            return [int(float(self.x.get().replace(",", "."))), int(float(self.y.get().replace(",", ".")))]
        except ValueError:
            raise self._error("coordonnées invalides.") from None


class RegionEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.value = list(value) if value else None
        self.full = tk.BooleanVar(value=value is None)
        ttk.Checkbutton(self.frame, text="Tout l'écran", variable=self.full,
                        command=self._refresh).pack(side="left")
        self.label = ttk.Label(self.frame, style="Muted.TLabel", width=24)
        self.label.pack(side="left", padx=8)
        self.pick = ttk.Button(self.frame, text="Sélectionner…", command=self._pick)
        self.pick.pack(side="left")
        tooltip(self.pick, "Limiter la recherche à une zone accélère la détection.")
        self.show = ttk.Button(self.frame, text="Montrer", command=self._show)
        self.show.pack(side="left", padx=(6, 0))
        self._refresh()

    def _refresh(self):
        if self.full.get() or not self.value:
            self.label.configure(text="(écran entier)")
        else:
            x, y, w, h = self.value
            self.label.configure(text=f"({x}, {y}) {w} × {h}")
        set_enabled([self.show], bool(self.value) and not self.full.get())

    def _pick(self):
        def done(result):
            if result is None:
                return
            x, y, w, h, _pixels = result
            self.value = [x, y, w, h]
            self.full.set(False)
            self._refresh()

        self.dialog.app.pick_region(done, parent=self.dialog)

    def _show(self):
        if self.value:
            self.dialog.app.flash_rect(*self.value)

    def get(self):
        if self.full.get() or not self.value:
            return None
        return list(self.value)


class ImageEditor(FieldEditor):
    full_row = False

    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.data = value or ""
        self._photo = None
        self.preview = tk.Label(self.frame, width=26, height=6, relief="flat", anchor="center",
                                background=palette()["field"], foreground=palette()["muted"])
        self.preview.grid(row=0, column=0, rowspan=3, sticky="nsew", padx=(0, 10))
        ttk.Button(self.frame, text="Capturer une zone de l'écran…",
                   command=self._capture).grid(row=0, column=1, sticky="ew")
        ttk.Button(self.frame, text="Charger un fichier…", command=self._load).grid(
            row=1, column=1, sticky="ew", pady=4)
        self.info = ttk.Label(self.frame, style="Muted.TLabel")
        self.info.grid(row=2, column=1, sticky="w")
        self._refresh()

    def _refresh(self):
        size = image_size(self.data)
        if not self.data or size is None:
            self.preview.configure(image="", text="Aucune image", width=26, height=6)
            self.info.configure(text="")
            self._photo = None
            return
        try:
            import base64
            import io

            from PIL import Image, ImageTk

            with Image.open(io.BytesIO(base64.b64decode(self.data))) as image:
                thumb = image.convert("RGB")
                thumb.thumbnail((220, 120))
                self._photo = ImageTk.PhotoImage(thumb, master=self.frame)
            self.preview.configure(image=self._photo, text="", width=224, height=124)
        except Exception:
            self.preview.configure(image="", text="Aperçu indisponible")
        self.info.configure(text=f"{size[0]} × {size[1]} pixels")

    def _capture(self):
        def done(result):
            if result is None:
                return
            _x, _y, _w, _h, pixels = result
            from ..core.screen import encode_png

            self.data = encode_png(pixels)
            self._refresh()

        self.dialog.app.pick_region(done, parent=self.dialog)

    def _load(self):
        path = filedialog.askopenfilename(
            parent=self.dialog, title="Choisir une image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("Tous les fichiers", "*")])
        if not path:
            return
        try:
            from ..core.screen import load_image_file

            self.data = load_image_file(path)
        except Exception as exc:
            messagebox.showerror("Image", f"Impossible de lire l'image :\n{exc}", parent=self.dialog)
            return
        self._refresh()

    def get(self):
        if not self.data:
            raise self._error("capturez ou chargez l'image à rechercher.")
        return self.data


class MacroEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        names = [n for n in dialog.app.library.names() if n != dialog.current_macro_name]
        self.var = tk.StringVar(value=value or (names[0] if names else ""))
        self.box = readonly_combobox(self.frame, self.var, names, width=30)
        self.box.pack(side="left")
        if not names:
            ttk.Label(self.frame, text="Aucune autre macro", style="Muted.TLabel").pack(side="left", padx=6)

    def get(self):
        name = self.var.get().strip()
        if not name:
            raise self._error("choisissez une macro.")
        return name


class WindowEditor(FieldEditor):
    def __init__(self, dialog, parent, spec, value):
        super().__init__(dialog, parent, spec, value)
        self.var = tk.StringVar(value=value or "")
        self.box = ttk.Combobox(self.frame, textvariable=self.var, width=40, postcommand=self._fill)
        self.box.pack(side="left")
        tooltip(self.box, "Tapez une partie du titre, ou choisissez parmi les fenêtres ouvertes.")

    def _fill(self):
        from ..core.system import list_window_titles

        self.box.configure(values=list_window_titles())

    def get(self):
        value = self.var.get().strip()
        if not value:
            raise self._error("indiquez le titre de la fenêtre.")
        return value


def _make_editor(dialog: "ActionDialog", parent: tk.Widget, spec: FieldSpec, params: Dict[str, Any]):
    value = params.get(spec.name, spec.default)
    kind = spec.kind
    if kind == "int":
        return NumberEditor(dialog, parent, spec, value)
    if kind == "float":
        return NumberEditor(dialog, parent, spec, value, is_float=True)
    if kind == "bool":
        return BoolEditor(dialog, parent, spec, value)
    if kind == "choice":
        return ChoiceEditor(dialog, parent, spec, value)
    if kind == "multiline":
        return MultilineEditor(dialog, parent, spec, value)
    if kind == "key":
        return KeyEditor(dialog, parent, spec, value, params.get("vk"), params.get("vk_os"))
    if kind == "combo":
        return ComboEditor(dialog, parent, spec, value)
    if kind == "color":
        return ColorEditor(dialog, parent, spec, value)
    if kind == "point":
        return PointEditor(dialog, parent, spec, value)
    if kind == "region":
        return RegionEditor(dialog, parent, spec, value)
    if kind == "image":
        return ImageEditor(dialog, parent, spec, value)
    if kind == "macro":
        return MacroEditor(dialog, parent, spec, value)
    if kind == "window":
        return WindowEditor(dialog, parent, spec, value)
    if kind == "text" and spec.name == "target":
        return TargetEditor(dialog, parent, spec, value)
    return TextEditor(dialog, parent, spec, value)


class ActionDialog(tk.Toplevel):
    def __init__(self, app, parent: tk.Misc, action: Action, is_new: bool = False,
                 current_macro_name: Optional[str] = None) -> None:
        super().__init__(parent)
        self.withdraw()
        self.app = app
        self.action = action.copy()
        self.spec = action.spec
        self.current_macro_name = current_macro_name
        self.result: Optional[Action] = None
        self.editors: Dict[str, FieldEditor] = {}
        prefix = "Nouvelle action" if is_new else "Modifier l'action"
        self.title(f"{prefix} — {self.spec.label}")
        self.resizable(False, False)
        try:
            self.transient(parent.winfo_toplevel())
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._build()
        self.bind("<Escape>", lambda _e: self._cancel())
        self.bind("<Return>", self._on_return)

    def _build(self) -> None:
        body = ttk.Frame(self, padding=(20, 16))
        body.pack(fill="both", expand=True)
        header = ttk.Frame(body)
        header.pack(fill="x")
        ttk.Label(header, text=f"{self.spec.icon}  {self.spec.label}", style="Subtitle.TLabel").pack(side="left")
        ttk.Label(header, text=self.spec.category, style="Muted.TLabel").pack(side="right")
        ttk.Separator(body).pack(fill="x", pady=10)

        form = ttk.Frame(body)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        row = 0
        for spec in self.spec.fields:
            if spec.kind == "hidden":
                continue
            editor = _make_editor(self, form, spec, self.action.params)
            self.editors[spec.name] = editor
            if editor.full_row:
                editor.frame.grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
            else:
                ttk.Label(form, text=spec.label).grid(row=row, column=0, sticky="nw", padx=(0, 14), pady=(7, 4))
                editor.frame.grid(row=row, column=1, sticky="w", pady=4)
            row += 1
            if spec.help:
                ttk.Label(form, text=spec.help, style="Small.TLabel", wraplength=430,
                          justify="left").grid(row=row, column=1 if not editor.full_row else 0,
                                               columnspan=1 if not editor.full_row else 2,
                                               sticky="w", pady=(0, 4))
                row += 1

        common = ttk.Frame(body)
        common.pack(fill="x", pady=(10, 0))
        self.delay = tk.StringVar(value=str(self.action.delay))
        if self.spec.has_delay:
            ttk.Label(common, text="Délai avant l'action").pack(side="left")
            number_box(common, self.delay, 0, 86_400_000, width=9, increment=10).pack(side="left", padx=6)
            ttk.Label(common, text="ms").pack(side="left")
        self.enabled = tk.BooleanVar(value=self.action.enabled)
        ttk.Checkbutton(common, text="Action active", variable=self.enabled).pack(side="right")

        ttk.Separator(body).pack(fill="x", pady=12)
        buttons = ttk.Frame(body)
        buttons.pack(fill="x")
        if self.spec.id in IMAGE_TYPES or self.spec.id in PIXEL_TYPES:
            test = ttk.Button(buttons, text="Tester maintenant", command=self._test)
            test.pack(side="left")
            tooltip(test, "Vérifie tout de suite si l'image ou la couleur est visible à l'écran.")
        ttk.Button(buttons, text="OK", style="Accent.TButton", width=10, command=self._ok).pack(side="right")
        ttk.Button(buttons, text="Annuler", command=self._cancel).pack(side="right", padx=(0, 8))
        if not self.editors:
            ttk.Label(form, text="Cette action n'a pas de réglage.", style="Muted.TLabel").grid(row=0, column=0)

    def _on_return(self, event) -> None:
        if isinstance(event.widget, tk.Text):
            return
        self._ok()

    def _collect(self) -> Optional[Dict[str, Any]]:
        params = dict(self.action.params)
        for name, editor in self.editors.items():
            try:
                params[name] = editor.get()
            except ValueError as exc:
                messagebox.showerror("Valeur invalide", str(exc), parent=self)
                editor.focus()
                return None
            if isinstance(editor, KeyEditor):
                params["vk"] = editor.vk
                params["vk_os"] = editor.vk_os
        return params

    def _test(self) -> None:
        params = self._collect()
        if params is None:
            return
        if self.spec.id in IMAGE_TYPES:
            self.app.test_image(self, params["image"], params["confidence"], params.get("region"))
        else:
            self.app.test_pixel(self, params["pos"], params["color"], params["tolerance"])

    def _ok(self) -> None:
        params = self._collect()
        if params is None:
            return
        delay = 0
        if self.spec.has_delay:
            try:
                delay = max(0, int(float(self.delay.get().replace(",", ".") or 0)))
            except ValueError:
                messagebox.showerror("Valeur invalide", "Délai avant l'action : nombre invalide.", parent=self)
                return
        action = Action.from_dict({"type": self.spec.id, **params, "delay": delay})
        action.enabled = bool(self.enabled.get())
        self.result = action
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def show(self) -> Optional[Action]:
        center_on(self, self.master)
        self.deiconify()
        self.lift()
        try:
            self.grab_set()
        except tk.TclError:
            pass
        first = next(iter(self.editors.values()), None)
        if first is not None:
            first.focus()
        self.wait_window(self)
        return self.result


def edit_action(app, parent: tk.Misc, action: Action, is_new: bool = False,
                current_macro_name: Optional[str] = None) -> Optional[Action]:
    return ActionDialog(app, parent, action, is_new, current_macro_name).show()


__all__ = ["ActionDialog", "edit_action", "editable_key_text", "COMMON_KEYS", "SPECIAL_KEYS"]
