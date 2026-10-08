"""Superposition plein écran : choisir un point (et sa couleur) ou une zone.

L'écran est d'abord photographié (fenêtres d'Autoclique masquées), puis la
capture est affichée par-dessus tout : un clic choisit un point, un glisser
délimite une zone. Échap ou clic droit annule.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Callable, Iterable, List, Optional

log = logging.getLogger("autoclique")

LOUPE_SOURCE = 15  # pixels de l'écran visibles dans la loupe
LOUPE_ZOOM = 8


class ScreenPicker:
    def __init__(
        self,
        root: tk.Tk,
        screen,
        mode: str,
        callback: Callable[[Optional[tuple]], None],
        hide: Iterable[tk.Misc] = (),
        on_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.root = root
        self.screen = screen
        self.mode = mode  # "point" ou "region"
        self.callback = callback
        self.on_error = on_error
        self.hidden: List[tk.Misc] = []
        for window in hide:
            try:
                if window.winfo_exists() and window.winfo_viewable():
                    self.hidden.append(window)
            except tk.TclError:
                pass
        self.top: Optional[tk.Toplevel] = None
        self.shot = None
        self.image = None
        self._photos = []
        self._start = None
        self._rect = None
        self._label = None
        self._loupe_item = None
        self._loupe_photo = None
        self._done = False

    def start(self) -> None:
        for window in self.hidden:
            try:
                if hasattr(window, "grab_release"):
                    window.grab_release()
                window.withdraw()
            except tk.TclError:
                pass
        self.root.update_idletasks()
        # Laisser au gestionnaire de fenêtres le temps d'effacer nos fenêtres.
        self.root.after(350, self._capture)

    def _capture(self) -> None:
        try:
            self.shot = self.screen.grab()
            self.image = self.shot.to_pil()
            self._build()
        except Exception as exc:  # capture impossible (Wayland, droits…)
            log.exception("Capture d'écran impossible")
            self._finish(None)
            if self.on_error:
                self.on_error(f"Capture d'écran impossible : {exc}")

    def _build(self) -> None:
        from PIL import ImageEnhance, ImageTk

        shot = self.shot
        width = int(round(shot.width / shot.scale))
        height = int(round(shot.height / shot.scale))
        display = self.image if shot.scale == 1 else self.image.resize((width, height))
        if self.mode == "region":
            display = ImageEnhance.Brightness(display).enhance(0.72)
        photo = ImageTk.PhotoImage(display, master=self.root)
        self._photos.append(photo)

        top = tk.Toplevel(self.root)
        top.withdraw()
        top.overrideredirect(True)
        top.geometry(f"{width}x{height}+{shot.left}+{shot.top}")
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass
        canvas = tk.Canvas(top, width=width, height=height, highlightthickness=0, borderwidth=0,
                           cursor="crosshair", background="black")
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        text = ("Cliquez sur la position voulue — Échap ou clic droit pour annuler"
                if self.mode == "point" else
                "Tracez un rectangle autour de la zone voulue — Échap ou clic droit pour annuler")
        self._banner(canvas, width, text)
        self._label = canvas.create_text(0, 0, text="", anchor="nw", fill="#ffffff",
                                         font=("TkDefaultFont", 10, "bold"))
        self._label_bg = canvas.create_rectangle(0, 0, 0, 0, fill="#000000", outline="", stipple="")
        canvas.tag_raise(self._label)
        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<ButtonPress-1>", self._on_press)
        canvas.bind("<B1-Motion>", self._on_drag)
        canvas.bind("<ButtonRelease-1>", self._on_release)
        canvas.bind("<ButtonPress-3>", lambda _e: self._finish(None))
        top.bind("<Escape>", lambda _e: self._finish(None))
        self.canvas = canvas
        self.top = top
        top.deiconify()
        top.lift()
        top.focus_force()
        try:
            top.grab_set()
        except tk.TclError:
            pass

    def _banner(self, canvas: tk.Canvas, width: int, text: str) -> None:
        item = canvas.create_text(width // 2, 28, text=text, fill="#ffffff",
                                  font=("TkDefaultFont", 12, "bold"))
        x0, y0, x1, y1 = canvas.bbox(item)
        back = canvas.create_rectangle(x0 - 14, y0 - 8, x1 + 14, y1 + 8, fill="#202020",
                                       outline="#57c8ff", width=2)
        canvas.tag_raise(item, back)

    # --- Évènements ---------------------------------------------------------------------

    def _screen_xy(self, event) -> tuple:
        return self.shot.left + int(event.x), self.shot.top + int(event.y)

    def _pixel(self, x: int, y: int) -> tuple:
        ix, iy = self.shot.to_image(x, y)
        ix = min(max(ix, 0), self.shot.width - 1)
        iy = min(max(iy, 0), self.shot.height - 1)
        r, g, b = self.shot.pixels[iy, ix]
        return int(r), int(g), int(b)

    def _show_label(self, event, text: str) -> None:
        canvas = self.canvas
        canvas.itemconfigure(self._label, text=text)
        x, y = event.x + 18, event.y + 18
        bbox = canvas.bbox(self._label) or (0, 0, 0, 0)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if x + w + 150 > canvas.winfo_width():
            x = event.x - w - 24
        if y + h + 150 > canvas.winfo_height():
            y = event.y - h - 24
        canvas.coords(self._label, x, y)
        canvas.coords(self._label_bg, x - 5, y - 3, x + w + 5, y + h + 3)
        canvas.tag_raise(self._label_bg)
        canvas.tag_raise(self._label)

    def _update_loupe(self, event, x: int, y: int) -> None:
        from PIL import Image, ImageTk

        half = LOUPE_SOURCE // 2
        ix, iy = self.shot.to_image(x, y)
        box = (ix - half, iy - half, ix + half + 1, iy + half + 1)
        crop = self.image.crop(box).resize((LOUPE_SOURCE * LOUPE_ZOOM,) * 2, Image.NEAREST)
        photo = ImageTk.PhotoImage(crop, master=self.root)
        self._loupe_photo = photo
        size = LOUPE_SOURCE * LOUPE_ZOOM
        lx, ly = event.x + 24, event.y + 48
        if lx + size > self.canvas.winfo_width():
            lx = event.x - size - 24
        if ly + size > self.canvas.winfo_height():
            ly = event.y - size - 48
        canvas = self.canvas
        if self._loupe_item is None:
            self._loupe_item = canvas.create_image(lx, ly, image=photo, anchor="nw")
            self._loupe_frame = canvas.create_rectangle(0, 0, 0, 0, outline="#57c8ff", width=2)
            self._loupe_center = canvas.create_rectangle(0, 0, 0, 0, outline="#ff3b30", width=2)
        canvas.itemconfigure(self._loupe_item, image=photo)
        canvas.coords(self._loupe_item, lx, ly)
        canvas.coords(self._loupe_frame, lx, ly, lx + size, ly + size)
        c0 = half * LOUPE_ZOOM
        canvas.coords(self._loupe_center, lx + c0, ly + c0, lx + c0 + LOUPE_ZOOM, ly + c0 + LOUPE_ZOOM)
        for item in (self._loupe_item, self._loupe_frame, self._loupe_center):
            canvas.tag_raise(item)

    def _on_motion(self, event) -> None:
        if self.mode != "point":
            x, y = self._screen_xy(event)
            self._show_label(event, f"{x}, {y}")
            return
        x, y = self._screen_xy(event)
        r, g, b = self._pixel(x, y)
        self._show_label(event, f"X {x}  Y {y}   #{r:02X}{g:02X}{b:02X}")
        try:
            self._update_loupe(event, x, y)
        except Exception:
            log.debug("Loupe indisponible", exc_info=True)

    def _on_press(self, event) -> None:
        if self.mode == "point":
            x, y = self._screen_xy(event)
            self._finish((x, y, self._pixel(x, y)))
            return
        self._start = (event.x, event.y)
        if self._rect is None:
            self._rect = self.canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                      outline="#57c8ff", width=2)
        self.canvas.coords(self._rect, event.x, event.y, event.x, event.y)

    def _on_drag(self, event) -> None:
        if self.mode != "region" or self._start is None:
            return
        x0, y0 = self._start
        self.canvas.coords(self._rect, x0, y0, event.x, event.y)
        self._show_label(event, f"{abs(event.x - x0)} × {abs(event.y - y0)}")

    def _on_release(self, event) -> None:
        if self.mode != "region" or self._start is None:
            return
        x0, y0 = self._start
        self._start = None
        left, right = sorted((x0, event.x))
        top, bottom = sorted((y0, event.y))
        width, height = right - left, bottom - top
        if width < 3 or height < 3:
            self.canvas.coords(self._rect, 0, 0, 0, 0)
            return
        sx, sy = self.shot.left + left, self.shot.top + top
        pixels = self.shot.crop(sx, sy, width, height)
        self._finish((sx, sy, width, height, pixels))

    def _finish(self, result: Optional[tuple]) -> None:
        if self._done:
            return
        self._done = True
        if self.top is not None:
            try:
                self.top.grab_release()
                self.top.destroy()
            except tk.TclError:
                pass
        for window in self.hidden:
            try:
                window.deiconify()
                window.lift()
            except tk.TclError:
                pass
        self._photos.clear()
        self.callback(result)


def flash_rectangle(root: tk.Misc, x: int, y: int, width: int, height: int,
                    color: str = "#ff3b30", duration: int = 1600, thickness: int = 3) -> None:
    """Encadre brièvement une zone de l'écran (quatre fines fenêtres)."""
    t = thickness
    sides = [
        (x - t, y - t, width + 2 * t, t),
        (x - t, y + height, width + 2 * t, t),
        (x - t, y, t, height),
        (x + width, y, t, height),
    ]
    windows = []
    for sx, sy, sw, sh in sides:
        window = tk.Toplevel(root)
        window.overrideredirect(True)
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        window.configure(background=color)
        window.geometry(f"{max(1, sw)}x{max(1, sh)}+{sx}+{sy}")
        windows.append(window)

    def close() -> None:
        for window in windows:
            try:
                window.destroy()
            except tk.TclError:
                pass

    root.after(duration, close)


def flash_point(root: tk.Misc, x: int, y: int, **kwargs) -> None:
    flash_rectangle(root, x - 10, y - 10, 21, 21, **kwargs)
