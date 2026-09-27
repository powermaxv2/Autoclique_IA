"""Capture d'écran, couleur des pixels et recherche d'image à l'écran.

La recherche d'image utilise OpenCV s'il est installé ; sinon une version
NumPy, plus lente mais sans dépendance lourde : corrélation normalisée
calculée par FFT sur une version réduite en niveaux de gris de l'écran, puis
vérification exacte, en couleur et à pleine résolution, autour des
meilleurs candidats.

Le score renvoyé est compris entre 0 et 1 :

* image « texturée » : corrélation croisée normalisée (1 = identique) ;
* image quasi unie : 1 - écart quadratique moyen / 100 (la corrélation
  n'a pas de sens sur une image sans contraste).
"""

from __future__ import annotations

import base64
import io
import math
import threading
from collections import OrderedDict
from typing import List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

LOW_TEXTURE_STD = 3.0
MAX_CANDIDATES = 12


class Match(NamedTuple):
    x: int  # centre de l'image trouvée (coordonnées écran)
    y: int
    score: float
    left: int
    top: int
    width: int
    height: int


class Shot:
    """Capture d'une zone de l'écran.

    ``pixels`` est un tableau RGB (hauteur, largeur, 3). ``scale`` vaut le
    nombre de pixels de l'image par unité de coordonnée écran (2 sur un
    écran Retina, 1 ailleurs).
    """

    def __init__(self, pixels: np.ndarray, left: int, top: int, scale: float = 1.0) -> None:
        self.pixels = pixels
        self.left = left
        self.top = top
        self.scale = scale or 1.0

    @property
    def width(self) -> int:
        return int(self.pixels.shape[1])

    @property
    def height(self) -> int:
        return int(self.pixels.shape[0])

    def to_screen(self, px: float, py: float) -> Tuple[int, int]:
        return (int(round(self.left + px / self.scale)), int(round(self.top + py / self.scale)))

    def to_image(self, x: float, y: float) -> Tuple[int, int]:
        return (int((x - self.left) * self.scale), int((y - self.top) * self.scale))

    def crop(self, left: int, top: int, width: int, height: int) -> np.ndarray:
        """Portion de la capture (coordonnées écran) en pixels de l'image."""
        x0, y0 = self.to_image(left, top)
        x1, y1 = self.to_image(left + width, top + height)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.width, x1), min(self.height, y1)
        return np.ascontiguousarray(self.pixels[y0:y1, x0:x1])

    def to_pil(self):
        from PIL import Image

        return Image.fromarray(np.ascontiguousarray(self.pixels, dtype=np.uint8))


# --- Encodage des images ---------------------------------------------------------------


def encode_png(pixels: np.ndarray) -> str:
    """Tableau RGB -> PNG encodé en base64 (stocké dans les macros)."""
    from PIL import Image

    buffer = io.BytesIO()
    image = Image.fromarray(np.ascontiguousarray(pixels, dtype=np.uint8))  # RGB déduit de la forme
    image.save(buffer, "PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def decode_png(data: str) -> np.ndarray:
    """PNG (ou autre format lisible par Pillow) en base64 -> tableau RGB."""
    from PIL import Image

    raw = base64.b64decode(data)
    with Image.open(io.BytesIO(raw)) as image:
        return np.array(image.convert("RGB"))


def load_image_file(path: str) -> str:
    """Charge un fichier image et le renvoie encodé en PNG base64."""
    from PIL import Image

    with Image.open(path) as image:
        return encode_png(np.array(image.convert("RGB")))


# --- Recherche d'image -----------------------------------------------------------------

_engine: Optional[str] = None


def available_engine() -> str:
    """« opencv » si OpenCV est installé, sinon « numpy »."""
    global _engine
    if _engine is None:
        try:
            import cv2  # noqa: F401

            _engine = "opencv"
        except Exception:
            _engine = "numpy"
    return _engine


def find_template(
    haystack: np.ndarray, needle: np.ndarray, engine: Optional[str] = None,
    threshold: float = 0.9,
) -> Optional[Tuple[int, int, float]]:
    """Meilleure position (x, y du coin supérieur gauche) de ``needle`` dans
    ``haystack`` et score associé, ou ``None`` si l'image est trop grande.

    ``threshold`` est la ressemblance visée : en dessous, la version NumPy
    refait une recherche complète avant de conclure."""
    if haystack.ndim != 3 or needle.ndim != 3:
        raise ValueError("Images RGB attendues.")
    big_h, big_w = haystack.shape[:2]
    h, w = needle.shape[:2]
    if h == 0 or w == 0 or h > big_h or w > big_w:
        return None
    # Contraste mesuré canal par canal : un aplat vert pur n'a aucune texture
    # même si ses composantes R, G et B sont très différentes.
    low_texture = float(needle.reshape(-1, 3).std(axis=0).max()) < LOW_TEXTURE_STD
    engine = engine or available_engine()
    if engine == "opencv":
        return _match_opencv(haystack, needle, low_texture)
    return _match_numpy(haystack, needle, low_texture, threshold)


def _rms_score(ssd: float, count: int) -> float:
    rms = math.sqrt(max(0.0, ssd) / max(1, count))
    return max(0.0, 1.0 - rms / 100.0)


def _match_opencv(haystack: np.ndarray, needle: np.ndarray, low_texture: bool):
    import cv2

    hay = np.ascontiguousarray(haystack, dtype=np.uint8)
    tpl = np.ascontiguousarray(needle, dtype=np.uint8)
    if low_texture:
        result = cv2.matchTemplate(hay, tpl, cv2.TM_SQDIFF)
        min_val, _max_val, min_loc, _max_loc = cv2.minMaxLoc(result)
        return int(min_loc[0]), int(min_loc[1]), _rms_score(min_val, tpl.size)
    result = cv2.matchTemplate(hay, tpl, cv2.TM_CCOEFF_NORMED)
    result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
    _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
    return int(max_loc[0]), int(max_loc[1]), float(min(max(max_val, 0.0), 1.0))


def _fast_len(n: int) -> int:
    """Plus petite taille >= n de la forme 2^a·3^b·5^c (FFT rapide)."""
    best = 1 << (n - 1).bit_length()
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            size = p35
            while size < n:
                size *= 2
            best = min(best, size)
            p35 *= 3
        p5 *= 5
    return best


def _gray(image: np.ndarray) -> np.ndarray:
    img = image.astype(np.float32)
    return img[..., 0] * 0.299 + img[..., 1] * 0.587 + img[..., 2] * 0.114


def _shrink(image: np.ndarray, factor: int) -> np.ndarray:
    if factor == 1:
        return image.astype(np.float32)
    h = image.shape[0] // factor * factor
    w = image.shape[1] // factor * factor
    cropped = image[:h, :w].astype(np.float32)
    shape = (h // factor, factor, w // factor, factor) + cropped.shape[2:]
    return cropped.reshape(shape).mean(axis=(1, 3))


def _box_sum(image: np.ndarray, h: int, w: int) -> np.ndarray:
    """Somme de ``image`` sur toutes les fenêtres h×w (image intégrale)."""
    integral = np.zeros((image.shape[0] + 1, image.shape[1] + 1), np.float64)
    np.cumsum(np.cumsum(image, axis=0, dtype=np.float64), axis=1, out=integral[1:, 1:])
    return integral[h:, w:] - integral[:-h, w:] - integral[h:, :-w] + integral[:-h, :-w]


def _ncc_map(image: np.ndarray, templ: np.ndarray) -> np.ndarray:
    """Corrélation normalisée (niveaux de gris) sur toutes les positions."""
    big_h, big_w = image.shape
    h, w = templ.shape
    centered = templ.astype(np.float64) - float(templ.mean())
    norm = math.sqrt(float((centered ** 2).sum()))
    out_shape = (big_h - h + 1, big_w - w + 1)
    if norm < 1e-6:
        return np.zeros(out_shape)
    fh, fw = _fast_len(big_h + h - 1), _fast_len(big_w + w - 1)
    spectrum = np.fft.rfft2(image, s=(fh, fw)) * np.fft.rfft2(centered[::-1, ::-1], s=(fh, fw))
    numerator = np.fft.irfft2(spectrum, s=(fh, fw))[h - 1:big_h, w - 1:big_w]
    s1 = _box_sum(image, h, w)
    s2 = _box_sum(image.astype(np.float64) ** 2, h, w)
    variance = np.maximum(s2 - s1 * s1 / (h * w), 0.0)
    denominator = norm * np.sqrt(variance)
    result = np.zeros(out_shape)
    np.divide(numerator, denominator, out=result, where=denominator > norm * 1e-3)
    return result


def _flat_color_map(image: np.ndarray, templ: np.ndarray) -> np.ndarray:
    """Score couleur approché d'une image quasi unie sur toutes les positions."""
    h, w = templ.shape[:2]
    colour = templ.reshape(-1, 3).mean(axis=0)
    spread = float(((templ - colour) ** 2).sum())
    ssd = np.full((image.shape[0] - h + 1, image.shape[1] - w + 1), spread)
    for c in range(3):
        channel = image[..., c].astype(np.float64)
        s1 = _box_sum(channel, h, w)
        s2 = _box_sum(channel ** 2, h, w)
        ssd += s2 - 2 * colour[c] * s1 + h * w * colour[c] ** 2
    rms = np.sqrt(np.maximum(ssd, 0.0) / (h * w * 3))
    return 1.0 - rms / 100.0


def _candidates(scores: np.ndarray, radius_y: int, radius_x: int) -> List[Tuple[int, int]]:
    work = scores.astype(np.float64, copy=True)
    best = float(work.max())
    found = []
    for _ in range(MAX_CANDIDATES):
        index = int(np.argmax(work))
        iy, ix = divmod(index, work.shape[1])
        value = work[iy, ix]
        if not np.isfinite(value) or (found and value < best - 0.25):
            break
        found.append((iy, ix))
        work[max(0, iy - radius_y):iy + radius_y + 1, max(0, ix - radius_x):ix + radius_x + 1] = -np.inf
    return found


def _window_scores(window: np.ndarray, templ: np.ndarray) -> np.ndarray:
    """Scores de ``templ`` sur toutes les positions d'une petite fenêtre.

    En niveaux de gris (tableaux 2D) : corrélation normalisée. En couleur
    (tableaux 3D, images quasi unies) : score d'écart quadratique moyen.
    """
    from numpy.lib.stride_tricks import sliding_window_view

    h, w = templ.shape[:2]
    if window.ndim == 3:
        view = sliding_window_view(window, (h, w), axis=(0, 1))  # (ny, nx, 3, h, w)
        t = templ.transpose(2, 0, 1)
        ssd = (np.einsum("ijckl,ijckl->ij", view, view)
               - 2 * np.einsum("ijckl,ckl->ij", view, t) + float((t ** 2).sum()))
        return 1.0 - np.sqrt(np.maximum(ssd, 0.0) / templ.size) / 100.0
    view = sliding_window_view(window, (h, w))  # (ny, nx, h, w)
    centered = templ - templ.mean()
    numerator = np.einsum("ijkl,kl->ij", view, centered)
    s1 = np.einsum("ijkl->ij", view)
    s2 = np.einsum("ijkl,ijkl->ij", view, view)
    variance = np.maximum(s2 - s1 * s1 / (h * w), 0.0)
    denominator = np.sqrt(variance * float((centered ** 2).sum()))
    out = np.zeros_like(numerator)
    np.divide(numerator, denominator, out=out, where=denominator > 1e-9)
    return out


def _exact_score(haystack: np.ndarray, needle: np.ndarray, x: int, y: int, low_texture: bool) -> float:
    h, w = needle.shape[:2]
    window = haystack[y:y + h, x:x + w].astype(np.float64)
    templ = needle.astype(np.float64)
    if low_texture:
        return _rms_score(float(((window - templ) ** 2).sum()), templ.size)
    a = window - window.mean(axis=(0, 1))
    b = templ - templ.mean(axis=(0, 1))
    denominator = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    if denominator <= 1e-9:
        return 0.0
    return max(0.0, min(1.0, float((a * b).sum()) / denominator))


def _match_numpy(haystack: np.ndarray, needle: np.ndarray, low_texture: bool,
                 threshold: float = 0.9):
    h, w = needle.shape[:2]
    factor = 4 if min(h, w) >= 48 else 2 if min(h, w) >= 16 else 1
    best = _search_numpy(haystack, needle, low_texture, factor)
    if factor > 1 and (best is None or best[2] < threshold):
        # Pas de correspondance nette à basse résolution (motifs très
        # semblables, comme du texte) : recherche complète en pleine résolution.
        full = _search_numpy(haystack, needle, low_texture, 1)
        if full is not None and (best is None or full[2] > best[2]):
            best = full
    return best


def _search_numpy(haystack: np.ndarray, needle: np.ndarray, low_texture: bool, factor: int):
    big_h, big_w = haystack.shape[:2]
    h, w = needle.shape[:2]
    if low_texture:
        # Une image quasi unie se compare en couleur.
        coarse = _flat_color_map(_shrink(haystack, factor), _shrink(needle, factor))
        search, templ = haystack, needle.astype(np.float64)
    else:
        gray, gray_needle = _gray(haystack), _gray(needle)
        coarse = _ncc_map(_shrink(gray, factor), _shrink(gray_needle, factor))
        search, templ = gray, gray_needle.astype(np.float64)
    small_h, small_w = h // factor, w // factor
    best: Optional[Tuple[int, int, float]] = None
    for cy, cx in _candidates(coarse, max(1, small_h // 2), max(1, small_w // 2)):
        x0, y0 = cx * factor, cy * factor
        y_lo, y_hi = max(0, min(y0 - factor, big_h - h)), min(big_h - h, y0 + factor)
        x_lo, x_hi = max(0, min(x0 - factor, big_w - w)), min(big_w - w, x0 + factor)
        window = search[y_lo:y_hi + h, x_lo:x_hi + w].astype(np.float64)
        scores = _window_scores(window, templ)
        iy, ix = divmod(int(np.argmax(scores)), scores.shape[1])
        x, y = x_lo + ix, y_lo + iy
        score = _exact_score(haystack, needle, x, y, low_texture)
        if best is None or score > best[2]:
            best = (x, y, score)
    return best


# --- Capture d'écran ---------------------------------------------------------------------


class ScreenCapture:
    """Accès à l'écran (via mss), avec un cache des images recherchées."""

    def __init__(self, engine: Optional[str] = None) -> None:
        self.engine = engine
        self._local = threading.local()
        self._templates: "OrderedDict[str, np.ndarray]" = OrderedDict()
        self._lock = threading.Lock()

    def _mss(self):
        instance = getattr(self._local, "mss", None)
        if instance is None:
            import mss

            factory = getattr(mss, "MSS", None) or mss.mss
            instance = factory()
            self._local.mss = instance
        return instance

    def virtual_screen(self) -> Tuple[int, int, int, int]:
        """(gauche, haut, largeur, hauteur) de l'ensemble des écrans."""
        monitor = self._mss().monitors[0]
        return monitor["left"], monitor["top"], monitor["width"], monitor["height"]

    def monitors(self) -> List[Tuple[int, int, int, int]]:
        return [(m["left"], m["top"], m["width"], m["height"]) for m in self._mss().monitors[1:]]

    def grab(self, region: Optional[Sequence[int]] = None) -> Shot:
        vl, vt, vw, vh = self.virtual_screen()
        if region is None:
            left, top, width, height = vl, vt, vw, vh
        else:
            left, top, width, height = (int(v) for v in region)
            right = min(left + width, vl + vw)
            bottom = min(top + height, vt + vh)
            left, top = max(left, vl), max(top, vt)
            width, height = right - left, bottom - top
            if width <= 0 or height <= 0:
                raise ValueError("La zone demandée est en dehors de l'écran.")
        raw = self._mss().grab({"left": left, "top": top, "width": width, "height": height})
        bgra = np.frombuffer(raw.bgra, dtype=np.uint8).reshape(raw.height, raw.width, 4)
        pixels = np.ascontiguousarray(bgra[:, :, 2::-1])
        return Shot(pixels, left, top, raw.width / float(width))

    def pixel(self, x: int, y: int) -> Tuple[int, int, int]:
        shot = self.grab((int(x), int(y), 1, 1))
        r, g, b = shot.pixels[0, 0]
        return int(r), int(g), int(b)

    def template(self, data: str) -> np.ndarray:
        with self._lock:
            cached = self._templates.get(data)
            if cached is not None:
                self._templates.move_to_end(data)
                return cached
        image = decode_png(data)
        with self._lock:
            self._templates[data] = image
            while len(self._templates) > 32:
                self._templates.popitem(last=False)
        return image

    def best_match(self, data: str, region: Optional[Sequence[int]] = None,
                   threshold: float = 0.9) -> Optional[Match]:
        """Meilleure correspondance de l'image, même si elle est mauvaise."""
        templ = self.template(data)
        shot = self.grab(region)
        found = find_template(shot.pixels, templ, self.engine, threshold)
        if found is None:
            return None
        px, py, score = found
        h, w = templ.shape[:2]
        left, top = shot.to_screen(px, py)
        right, bottom = shot.to_screen(px + w, py + h)
        cx, cy = shot.to_screen(px + w / 2.0, py + h / 2.0)
        return Match(cx, cy, float(score), left, top, right - left, bottom - top)

    def locate(self, data: str, confidence: float = 0.9,
               region: Optional[Sequence[int]] = None) -> Optional[Match]:
        """Position de l'image si la ressemblance atteint ``confidence``."""
        match = self.best_match(data, region, confidence)
        if match is not None and match.score >= confidence:
            return match
        return None
