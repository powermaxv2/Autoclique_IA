"""Types d'actions de macro : schéma, valeurs par défaut et descriptions.

Chaque type d'action est décrit par un :class:`ActionType` listant ses champs
(:class:`FieldSpec`). Ce schéma sert à la fois à valider les fichiers de
macros, à générer les formulaires de l'éditeur et à afficher un résumé
lisible de chaque action.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .keys import MOUSE_BUTTONS, PLATFORM, KeyRef, hotkey_label, key_label

# Types de champs reconnus par l'éditeur :
#   int, float, bool, choice, text, multiline, key, combo, color, image,
#   point (paire x, y), region (x, y, largeur, hauteur), macro, window, hidden


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: str
    default: Any = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    choices: Tuple[Tuple[Any, str], ...] = ()
    unit: str = ""
    optional: bool = False
    help: str = ""


@dataclass(frozen=True)
class ActionType:
    id: str
    label: str
    category: str
    fields: Tuple[FieldSpec, ...] = ()
    has_delay: bool = True
    block: str = ""  # open_loop, close_loop, open_if, else, close_if, break
    icon: str = "•"
    help: str = ""

    def field(self, name: str) -> Optional[FieldSpec]:
        for f in self.fields:
            if f.name == name:
                return f
        return None


BUTTON_CHOICES = tuple(MOUSE_BUTTONS.items())
COUNT_CHOICES = ((1, "Simple"), (2, "Double"), (3, "Triple"))
TIMEOUT_CHOICES = (("continue", "Continuer la macro"), ("stop", "Arrêter la macro"))


def _button() -> FieldSpec:
    return FieldSpec("button", "Bouton", "choice", "left", choices=BUTTON_CHOICES)


def _pos(optional: bool = True, label: str = "Position") -> FieldSpec:
    return FieldSpec(
        "pos", label, "point", None if optional else [0, 0], optional=optional,
        help="Cochez « Position actuelle » pour agir là où se trouve le curseur." if optional else "",
    )


def _key(default: str = "enter") -> Tuple[FieldSpec, ...]:
    return (
        FieldSpec("key", "Touche", "key", default),
        FieldSpec("vk", "", "hidden", None),
        FieldSpec("vk_os", "", "hidden", None),
    )


def _image_fields() -> Tuple[FieldSpec, ...]:
    return (
        FieldSpec("image", "Image à trouver", "image", ""),
        FieldSpec(
            "confidence", "Ressemblance minimale", "int", 90, 50, 100, unit="%",
            help="100 % = identique au pixel près. Baissez un peu si l'image n'est pas trouvée.",
        ),
        FieldSpec("region", "Zone de recherche", "region", None, optional=True),
    )


def _timeout_fields() -> Tuple[FieldSpec, ...]:
    return (
        FieldSpec("timeout", "Délai maximum", "float", 30.0, 0, 86400, unit="s",
                  help="0 = attendre indéfiniment."),
        FieldSpec("on_timeout", "Si le délai est dépassé", "choice", "continue",
                  choices=TIMEOUT_CHOICES),
    )


def _pixel_fields() -> Tuple[FieldSpec, ...]:
    return (
        _pos(optional=False, label="Pixel"),
        FieldSpec("color", "Couleur", "color", "#FFFFFF"),
        FieldSpec("tolerance", "Tolérance", "int", 10, 0, 255,
                  help="Écart maximal accepté sur chaque composante (0 à 255)."),
    )


_TYPES: List[ActionType] = [
    # --- Souris -----------------------------------------------------------
    ActionType("click", "Clic", "Souris", (
        _button(),
        FieldSpec("count", "Type de clic", "choice", 1, choices=COUNT_CHOICES),
        _pos(),
        FieldSpec("hold", "Durée d'appui", "int", 0, 0, 600000, unit="ms"),
    ), icon="◉"),
    ActionType("mouse_down", "Appuyer (souris)", "Souris", (_button(), _pos()), icon="▼"),
    ActionType("mouse_up", "Relâcher (souris)", "Souris", (_button(), _pos()), icon="▲"),
    ActionType("move", "Déplacer la souris", "Souris", (
        _pos(optional=False),
        FieldSpec("relative", "Déplacement relatif à la position actuelle", "bool", False),
        FieldSpec("duration", "Durée du mouvement", "int", 0, 0, 60000, unit="ms",
                  help="0 = déplacement instantané."),
    ), icon="➜"),
    ActionType("scroll", "Molette", "Souris", (
        FieldSpec("dy", "Crans verticaux (+ = haut, - = bas)", "int", -3, -1000, 1000),
        FieldSpec("dx", "Crans horizontaux (+ = droite)", "int", 0, -1000, 1000),
        _pos(),
    ), icon="↕"),
    # --- Clavier ----------------------------------------------------------
    ActionType("key_press", "Touche", "Clavier", _key() + (
        FieldSpec("hold", "Durée d'appui", "int", 50, 0, 600000, unit="ms",
                  help="Un appui d'au moins 30 ms est mieux reconnu par les jeux."),
    ), icon="⌨"),
    ActionType("key_down", "Appuyer (touche)", "Clavier", _key("shift"), icon="▼"),
    ActionType("key_up", "Relâcher (touche)", "Clavier", _key("shift"), icon="▲"),
    ActionType("hotkey", "Combinaison de touches", "Clavier", (
        FieldSpec("keys", "Combinaison", "combo", "ctrl+c",
                  help="Exemples : Ctrl+C, Ctrl+Maj+Échap, Alt+Tab."),
    ), icon="⌘"),
    ActionType("type_text", "Taper du texte", "Clavier", (
        FieldSpec("text", "Texte", "multiline", ""),
        FieldSpec("interval", "Pause entre les caractères", "int", 0, 0, 10000, unit="ms"),
    ), icon="✎"),
    # --- Attente ------------------------------------------------------------
    ActionType("wait", "Attendre", "Attente", (
        FieldSpec("duration", "Durée", "int", 1000, 0, 86400000, unit="ms"),
        FieldSpec("random", "Variation aléatoire ±", "int", 0, 0, 86400000, unit="ms"),
    ), icon="⏱"),
    ActionType("wait_pixel", "Attendre une couleur", "Attente",
               _pixel_fields() + _timeout_fields(), icon="◐"),
    ActionType("wait_image", "Attendre une image", "Attente",
               _image_fields() + _timeout_fields(), icon="▣"),
    # --- Image et couleur ------------------------------------------------------
    ActionType("click_image", "Cliquer sur une image", "Image et couleur", _image_fields() + (
        _button(),
        FieldSpec("count", "Type de clic", "choice", 1, choices=COUNT_CHOICES),
        FieldSpec("offset_x", "Décalage horizontal depuis le centre", "int", 0, -10000, 10000, unit="px"),
        FieldSpec("offset_y", "Décalage vertical depuis le centre", "int", 0, -10000, 10000, unit="px"),
    ) + _timeout_fields(), icon="▣"),
    ActionType("if_image", "Si une image est visible", "Image et couleur", _image_fields() + (
        FieldSpec("negate", "Inverser (si l'image N'EST PAS visible)", "bool", False),
    ), block="open_if", icon="?"),
    ActionType("if_pixel", "Si une couleur est présente", "Image et couleur", _pixel_fields() + (
        FieldSpec("negate", "Inverser (si la couleur N'EST PAS présente)", "bool", False),
    ), block="open_if", icon="?"),
    # --- Contrôle -----------------------------------------------------------
    ActionType("loop_start", "Répéter", "Contrôle", (
        FieldSpec("count", "Nombre de répétitions", "int", 10, 0, 10_000_000,
                  help="0 = répéter indéfiniment (utilisez « Sortir de la boucle » ou l'arrêt)."),
    ), has_delay=False, block="open_loop", icon="↻"),
    ActionType("loop_end", "Fin de répétition", "Contrôle", has_delay=False,
               block="close_loop", icon="↻"),
    ActionType("break", "Sortir de la boucle", "Contrôle", has_delay=False,
               block="break", icon="⤴"),
    ActionType("else", "Sinon", "Contrôle", has_delay=False, block="else", icon="↳"),
    ActionType("end_if", "Fin si", "Contrôle", has_delay=False, block="close_if", icon="↲"),
    ActionType("run_macro", "Lancer une macro", "Contrôle", (
        FieldSpec("macro", "Macro", "macro", ""),
        FieldSpec("repeat", "Nombre d'exécutions", "int", 1, 1, 1_000_000),
    ), icon="▶"),
    ActionType("stop", "Arrêter la macro", "Contrôle", has_delay=False, icon="■"),
    ActionType("comment", "Commentaire", "Contrôle", (
        FieldSpec("text", "Texte", "text", ""),
    ), has_delay=False, icon="#"),
    # --- Système ------------------------------------------------------------
    ActionType("open", "Ouvrir un programme, fichier ou site", "Système", (
        FieldSpec("target", "Programme, fichier ou adresse web", "text", ""),
        FieldSpec("args", "Arguments (facultatif)", "text", ""),
    ), icon="↗"),
    ActionType("focus_window", "Activer une fenêtre", "Système", (
        FieldSpec("title", "Titre de la fenêtre (ou une partie)", "window", "",
                  help="Sous macOS, indiquez le nom de l'application."),
        FieldSpec("timeout", "Attendre la fenêtre au maximum", "float", 5.0, 0, 3600, unit="s"),
        FieldSpec("on_timeout", "Si la fenêtre est introuvable", "choice", "continue",
                  choices=TIMEOUT_CHOICES),
    ), icon="▭"),
]

ACTION_TYPES: Dict[str, ActionType] = {t.id: t for t in _TYPES}
CATEGORIES: Tuple[str, ...] = (
    "Souris", "Clavier", "Attente", "Image et couleur", "Contrôle", "Système",
)

# Actions qui ouvrent un bloc et l'action de fermeture insérée automatiquement.
BLOCK_CLOSERS = {"loop_start": "loop_end", "if_image": "end_if", "if_pixel": "end_if"}


def action_type(type_id: str) -> ActionType:
    try:
        return ACTION_TYPES[type_id]
    except KeyError:
        raise ValueError(f"Type d'action inconnu : « {type_id} ».") from None


# --- Validation des valeurs ------------------------------------------------------


def _clamp(value: float, spec: FieldSpec) -> float:
    if spec.minimum is not None and value < spec.minimum:
        value = spec.minimum
    if spec.maximum is not None and value > spec.maximum:
        value = spec.maximum
    return value


def coerce_value(spec: FieldSpec, value: Any) -> Any:
    """Convertit ``value`` au type attendu par ``spec`` (valeur par défaut si
    la conversion est impossible)."""
    default = copy.deepcopy(spec.default)
    kind = spec.kind
    try:
        if kind == "int":
            if isinstance(value, bool):
                raise TypeError
            return int(_clamp(int(round(float(value))), spec))
        if kind == "float":
            if isinstance(value, bool):
                raise TypeError
            return float(_clamp(float(value), spec))
        if kind == "bool":
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "vrai", "oui", "yes")
            return bool(value)
        if kind == "choice":
            for choice, _label in spec.choices:
                if value == choice or str(value) == str(choice):
                    return choice
            return default
        if kind in ("text", "multiline", "key", "combo", "image", "macro", "window"):
            return "" if value is None else str(value)
        if kind == "color":
            return normalize_color(str(value))
        if kind == "point":
            if value is None:
                if spec.optional:
                    return None
                return default
            x, y = value
            return [int(round(float(x))), int(round(float(y)))]
        if kind == "region":
            if value is None:
                return None
            x, y, w, h = (int(round(float(v))) for v in value)
            if w <= 0 or h <= 0:
                return None
            return [x, y, w, h]
        if kind == "hidden":
            return value
    except (TypeError, ValueError):
        return default
    return value


def normalize_color(text: str) -> str:
    """``"#abc"``, ``"aabbcc"`` ou ``"rgb(1,2,3)"`` -> ``"#AABBCC"``."""
    s = text.strip()
    if s.lower().startswith("rgb"):
        inner = s[s.index("(") + 1: s.rindex(")")]
        r, g, b = (max(0, min(255, int(float(v)))) for v in inner.split(","))
        return f"#{r:02X}{g:02X}{b:02X}"
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"Couleur invalide : « {text} ».")
    int(s, 16)
    return "#" + s.upper()


def color_to_rgb(color: str) -> Tuple[int, int, int]:
    s = normalize_color(color).lstrip("#")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def rgb_to_color(rgb) -> str:
    r, g, b = (int(v) for v in rgb[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


# --- Action --------------------------------------------------------------------


@dataclass
class Action:
    """Une étape de macro."""

    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    delay: int = 0  # millisecondes d'attente avant l'action
    enabled: bool = True

    @property
    def spec(self) -> ActionType:
        return action_type(self.type)

    @classmethod
    def new(cls, type_id: str, delay: int = 0, **params: Any) -> "Action":
        spec = action_type(type_id)
        values = {f.name: copy.deepcopy(f.default) for f in spec.fields}
        for name, value in params.items():
            f = spec.field(name)
            if f is None:
                raise ValueError(f"Paramètre inconnu « {name} » pour « {spec.label} ».")
            values[name] = coerce_value(f, value)
        return cls(type_id, values, delay if spec.has_delay else 0)

    def copy(self) -> "Action":
        return Action(self.type, copy.deepcopy(self.params), self.delay, self.enabled)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {"type": self.type}
        if self.spec.has_delay:
            data["delay"] = self.delay
        for f in self.spec.fields:
            value = self.params.get(f.name, f.default)
            if f.kind == "hidden" and value is None:
                continue
            data[f.name] = copy.deepcopy(value)
        if not self.enabled:
            data["enabled"] = False
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Action":
        if not isinstance(data, dict) or "type" not in data:
            raise ValueError("Action invalide : type manquant.")
        spec = action_type(str(data["type"]))
        params = {}
        for f in spec.fields:
            params[f.name] = coerce_value(f, data[f.name]) if f.name in data else copy.deepcopy(f.default)
        delay = 0
        if spec.has_delay:
            try:
                delay = max(0, int(round(float(data.get("delay", 0)))))
            except (TypeError, ValueError):
                delay = 0
        enabled = data.get("enabled", True) is not False
        return cls(spec.id, params, delay, enabled)

    def key_ref(self) -> KeyRef:
        """Touche d'une action clavier, avec le code virtuel s'il s'applique."""
        vk = self.params.get("vk")
        if vk is not None and self.params.get("vk_os") == PLATFORM:
            return KeyRef(self.params.get("key", ""), int(vk))
        return KeyRef(self.params.get("key", ""))

    def describe(self) -> str:
        try:
            return _describe(self)
        except Exception:  # un résumé ne doit jamais faire échouer l'affichage
            return ""


# --- Descriptions lisibles ---------------------------------------------------------


def format_ms(ms: float) -> str:
    """Durée lisible : ``"250 ms"``, ``"1,5 s"``, ``"2 min 5 s"``."""
    ms = float(ms)
    if ms < 1000:
        return f"{ms:.0f} ms"
    seconds = ms / 1000
    if seconds < 60:
        text = f"{seconds:.2f}".rstrip("0").rstrip(".")
        return text.replace(".", ",") + " s"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes} min {sec} s" if sec else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


def format_seconds(seconds: float) -> str:
    return format_ms(float(seconds) * 1000)


def _pos_text(pos) -> str:
    if pos is None:
        return "à la position du curseur"
    return f"à ({pos[0]}, {pos[1]})"


def _image_text(p: Dict[str, Any]) -> str:
    size = image_size(p.get("image", ""))
    text = f"image {size[0]}×{size[1]}" if size else "aucune image"
    text += f", ressemblance ≥ {p.get('confidence', 90)} %"
    if p.get("region"):
        x, y, w, h = p["region"]
        text += f", zone ({x}, {y}) {w}×{h}"
    return text


def _timeout_text(p: Dict[str, Any]) -> str:
    timeout = float(p.get("timeout", 0) or 0)
    if timeout <= 0:
        return "sans limite"
    action = "puis arrêt" if p.get("on_timeout") == "stop" else "puis on continue"
    return f"max {format_seconds(timeout)} {action}"


def _button_text(p: Dict[str, Any]) -> str:
    return MOUSE_BUTTONS.get(p.get("button", "left"), p.get("button", "")).split(" (")[0].lower()


def image_size(b64: str) -> Optional[Tuple[int, int]]:
    """Dimensions d'une image PNG encodée en base64 (lecture de l'en-tête)."""
    if not b64:
        return None
    import base64
    import struct

    try:
        head = base64.b64decode(b64[:64] + "=" * (-len(b64[:64]) % 4))
    except Exception:
        return None
    if head[:8] != b"\x89PNG\r\n\x1a\n" or len(head) < 24:
        return None
    width, height = struct.unpack(">II", head[16:24])
    return int(width), int(height)


def _describe(a: Action) -> str:
    p = a.params
    t = a.type
    if t == "click":
        kind = {1: "Clic", 2: "Double clic", 3: "Triple clic"}.get(p.get("count", 1), "Clic")
        text = f"{kind} {_button_text(p)} {_pos_text(p.get('pos'))}"
        if p.get("hold"):
            text += f", appui {format_ms(p['hold'])}"
        return text
    if t in ("mouse_down", "mouse_up"):
        return f"Bouton {_button_text(p)} {_pos_text(p.get('pos'))}"
    if t == "move":
        x, y = p.get("pos") or (0, 0)
        text = f"De ({x:+d}, {y:+d})" if p.get("relative") else f"Vers ({x}, {y})"
        if p.get("duration"):
            text += f" en {format_ms(p['duration'])}"
        return text
    if t == "scroll":
        parts = []
        dy, dx = int(p.get("dy", 0)), int(p.get("dx", 0))
        if dy:
            parts.append(f"{'↑' if dy > 0 else '↓'} {abs(dy)} cran{'s' if abs(dy) > 1 else ''}")
        if dx:
            parts.append(f"{'→' if dx > 0 else '←'} {abs(dx)} cran{'s' if abs(dx) > 1 else ''}")
        text = ", ".join(parts) or "aucun défilement"
        if p.get("pos") is not None:
            text += f" {_pos_text(p['pos'])}"
        return text
    if t == "key_press":
        text = key_label(p.get("key", ""))
        if p.get("hold"):
            text += f" (appui {format_ms(p['hold'])})"
        return text
    if t in ("key_down", "key_up"):
        return key_label(p.get("key", ""))
    if t == "hotkey":
        return hotkey_label(p.get("keys", ""))
    if t == "type_text":
        text = p.get("text", "").replace("\n", "⏎")
        if len(text) > 60:
            text = text[:57] + "…"
        suffix = f" ({format_ms(p['interval'])} entre les caractères)" if p.get("interval") else ""
        return f"« {text} »{suffix}"
    if t == "wait":
        text = format_ms(p.get("duration", 0))
        if p.get("random"):
            text += f" ± {format_ms(p['random'])}"
        return text
    if t == "wait_pixel":
        x, y = p.get("pos") or (0, 0)
        return f"({x}, {y}) = {p.get('color', '')} ± {p.get('tolerance', 0)}, {_timeout_text(p)}"
    if t == "if_pixel":
        x, y = p.get("pos") or (0, 0)
        verb = "≠" if p.get("negate") else "="
        return f"({x}, {y}) {verb} {p.get('color', '')} ± {p.get('tolerance', 0)}"
    if t == "wait_image":
        return f"{_image_text(p)}, {_timeout_text(p)}"
    if t == "click_image":
        kind = {1: "clic", 2: "double clic", 3: "triple clic"}.get(p.get("count", 1), "clic")
        text = f"{_image_text(p)} → {kind} {_button_text(p)}"
        if p.get("offset_x") or p.get("offset_y"):
            text += f" décalé de ({p.get('offset_x', 0):+d}, {p.get('offset_y', 0):+d})"
        return f"{text}, {_timeout_text(p)}"
    if t == "if_image":
        verb = "absente" if p.get("negate") else "visible"
        return f"{_image_text(p)} {verb}"
    if t == "loop_start":
        count = int(p.get("count", 0))
        return "indéfiniment" if count <= 0 else f"{count} fois"
    if t == "run_macro":
        repeat = int(p.get("repeat", 1))
        return f"« {p.get('macro', '')} »" + (f" × {repeat}" if repeat > 1 else "")
    if t == "comment":
        return p.get("text", "")
    if t == "open":
        text = p.get("target", "")
        if p.get("args"):
            text += " " + p["args"]
        return text
    if t == "focus_window":
        return f"« {p.get('title', '')} », {_timeout_text(p)}"
    return ""


def uses_external_program(actions: List[Action]) -> List[str]:
    """Cibles des actions « Ouvrir » (pour avertir avant d'importer une macro)."""
    return [a.params.get("target", "") for a in actions if a.type == "open"]
