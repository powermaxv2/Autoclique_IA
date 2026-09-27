"""Noms des touches du clavier, des boutons de souris et des raccourcis.

Ce module ne dépend pas de pynput : il ne manipule que des chaînes, ce qui
permet de l'utiliser et de le tester sans affichage.

Une touche est désignée par une chaîne :

* touche spéciale : nom issu de ``pynput.keyboard.Key`` (``"enter"``, ``"f5"``…) ;
* caractère : un seul caractère (``"a"``, ``"é"``, ``"1"``), les lettres
  étant toujours en minuscules (la touche Maj est une touche à part) ;
* pavé numérique : ``"num0"`` … ``"num9"``, ``"num_add"``… ;
* code virtuel brut : ``"vk:65"``.

Un raccourci s'écrit ``"ctrl+shift+f6"`` : zéro ou plusieurs modificateurs
suivis d'une touche principale ou d'un bouton de souris (``"mouse_x1"``).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

if sys.platform.startswith("win"):
    PLATFORM = "win32"
elif sys.platform == "darwin":
    PLATFORM = "darwin"
else:
    PLATFORM = "linux"

SPECIAL_KEYS: Dict[str, str] = {
    "enter": "Entrée",
    "esc": "Échap",
    "space": "Espace",
    "tab": "Tab",
    "backspace": "Retour arrière",
    "delete": "Suppr",
    "insert": "Inser",
    "home": "Début",
    "end": "Fin",
    "page_up": "Page précédente",
    "page_down": "Page suivante",
    "up": "Flèche haut",
    "down": "Flèche bas",
    "left": "Flèche gauche",
    "right": "Flèche droite",
    "shift": "Maj",
    "shift_l": "Maj gauche",
    "shift_r": "Maj droite",
    "ctrl": "Ctrl",
    "ctrl_l": "Ctrl gauche",
    "ctrl_r": "Ctrl droit",
    "alt": "Alt",
    "alt_l": "Alt gauche",
    "alt_r": "Alt droit",
    "alt_gr": "Alt Gr",
    "cmd": "Windows/Cmd",
    "cmd_l": "Windows/Cmd gauche",
    "cmd_r": "Windows/Cmd droit",
    "caps_lock": "Verr. Maj",
    "num_lock": "Verr. Num",
    "scroll_lock": "Arrêt défil.",
    "print_screen": "Impr. écran",
    "pause": "Pause",
    "menu": "Menu contextuel",
    **{f"f{i}": f"F{i}" for i in range(1, 25)},
    "media_play_pause": "Lecture/Pause",
    "media_stop": "Arrêt (média)",
    "media_next": "Piste suivante",
    "media_previous": "Piste précédente",
    "media_volume_up": "Volume +",
    "media_volume_down": "Volume -",
    "media_volume_mute": "Muet",
}

NUMPAD_KEYS: Dict[str, str] = {
    **{f"num{i}": f"Pavé num. {i}" for i in range(10)},
    "num_add": "Pavé num. +",
    "num_sub": "Pavé num. -",
    "num_mul": "Pavé num. *",
    "num_div": "Pavé num. /",
    "num_dec": "Pavé num. ,",
}

# Codes des touches du pavé numérique : codes virtuels Windows, keysyms X11
# et codes de touches macOS.
_NUMPAD_CODES: Dict[str, Dict[str, int]] = {
    "win32": {
        **{f"num{i}": 0x60 + i for i in range(10)},
        "num_mul": 0x6A,
        "num_add": 0x6B,
        "num_sub": 0x6D,
        "num_dec": 0x6E,
        "num_div": 0x6F,
    },
    "linux": {
        **{f"num{i}": 0xFFB0 + i for i in range(10)},
        "num_mul": 0xFFAA,
        "num_add": 0xFFAB,
        "num_sub": 0xFFAD,
        "num_dec": 0xFFAE,
        "num_div": 0xFFAF,
    },
    "darwin": {
        "num0": 0x52, "num1": 0x53, "num2": 0x54, "num3": 0x55, "num4": 0x56,
        "num5": 0x57, "num6": 0x58, "num7": 0x59, "num8": 0x5B, "num9": 0x5C,
        "num_dec": 0x41, "num_mul": 0x43, "num_add": 0x45, "num_sub": 0x4E,
        "num_div": 0x4B,
    },
}
_NUMPAD_NAMES = {
    platform: {code: name for name, code in codes.items()}
    for platform, codes in _NUMPAD_CODES.items()
}

MOUSE_BUTTONS: Dict[str, str] = {
    "left": "Gauche",
    "right": "Droit",
    "middle": "Milieu",
    "x1": "Latéral 1 (précédent)",
    "x2": "Latéral 2 (suivant)",
}

# Boutons de souris utilisables comme raccourci (jamais gauche ni droit, pour
# que l'interface reste cliquable).
MOUSE_HOTKEYS: Dict[str, str] = {
    "mouse_middle": "Clic milieu",
    "mouse_x1": "Souris 4",
    "mouse_x2": "Souris 5",
}

MODIFIER_ORDER = ("ctrl", "alt", "shift", "cmd")
MODIFIER_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Maj", "cmd": "Win"}
if PLATFORM == "darwin":
    MODIFIER_LABELS["cmd"] = "Cmd"

# Variante gauche/droite d'un modificateur -> modificateur générique.
MODIFIER_OF: Dict[str, str] = {
    "ctrl": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "cmd": "cmd", "cmd_l": "cmd", "cmd_r": "cmd",
}

_ALIASES: Dict[str, str] = {
    "entrée": "enter", "entree": "enter", "return": "enter", "retour": "enter",
    "échap": "esc", "echap": "esc", "escape": "esc", "échappement": "esc",
    "espace": "space", "spacebar": "space", "barre d'espace": "space",
    "tabulation": "tab",
    "retour arrière": "backspace", "retour arriere": "backspace",
    "suppr": "delete", "supprimer": "delete", "del": "delete",
    "inser": "insert", "ins": "insert", "insérer": "insert", "inserer": "insert",
    "début": "home", "debut": "home", "origine": "home",
    "fin": "end",
    "pageup": "page_up", "pgup": "page_up", "page up": "page_up",
    "pagedown": "page_down", "pgdn": "page_down", "page down": "page_down",
    "haut": "up", "bas": "down", "gauche": "left", "droite": "right",
    "fleche haut": "up", "fleche bas": "down",
    "fleche gauche": "left", "fleche droite": "right",
    "maj": "shift", "majuscule": "shift",
    "control": "ctrl", "contrôle": "ctrl", "controle": "ctrl", "ctl": "ctrl",
    "option": "alt", "altgr": "alt_gr", "alt gr": "alt_gr",
    "win": "cmd", "windows": "cmd", "super": "cmd", "meta": "cmd",
    "command": "cmd", "commande": "cmd",
    "verr maj": "caps_lock", "capslock": "caps_lock",
    "verr num": "num_lock", "numlock": "num_lock",
    "impr": "print_screen", "printscreen": "print_screen", "prtsc": "print_screen",
    "break": "pause",
    "plus": "+", "moins": "-",
}
for _name, _label in list(SPECIAL_KEYS.items()) + list(NUMPAD_KEYS.items()):
    _ALIASES.setdefault(_label.lower(), _name)


@dataclass(frozen=True)
class KeyRef:
    """Touche à envoyer : nom lisible et, éventuellement, code virtuel.

    ``vk`` n'est renseigné que pour les touches enregistrées sous Windows :
    envoyer le code virtuel reproduit exactement la touche physique, ce qui
    fonctionne mieux dans les jeux que l'envoi d'un caractère.
    """

    name: str
    vk: Optional[int] = None


def numpad_code(name: str, platform: str = PLATFORM) -> Optional[int]:
    """Code système d'une touche du pavé numérique (ou ``None``)."""
    return _NUMPAD_CODES.get(platform, {}).get(name)


def numpad_name(code: Optional[int], platform: str = PLATFORM) -> Optional[str]:
    """Nom (``"num1"``…) correspondant à un code système, sinon ``None``."""
    if code is None:
        return None
    return _NUMPAD_NAMES.get(platform, {}).get(code)


def normalize_key(text: str) -> str:
    """Convertit une saisie utilisateur en nom de touche normalisé.

    Accepte les noms pynput (``"enter"``, ``"Key.f5"``, ``"<f5>"``), les
    libellés français (``"Entrée"``, ``"Échap"``), un caractère unique ou un
    code virtuel ``"vk:65"``. Lève ``ValueError`` si la touche est inconnue.
    """
    if text == " ":
        return "space"
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Aucune touche indiquée.")
    if len(raw) == 1:
        return raw.lower() if raw.isalpha() else raw
    low = raw.lower()
    if low.startswith("key."):
        low = low[4:]
    if low.startswith("<") and low.endswith(">") and len(low) > 2:
        low = low[1:-1]
        if low.isdigit():
            return f"vk:{int(low)}"
    if low in SPECIAL_KEYS or low in NUMPAD_KEYS:
        return low
    if low in _ALIASES:
        return _ALIASES[low]
    if low.startswith("vk:") and low[3:].strip().isdigit():
        return f"vk:{int(low[3:])}"
    raise ValueError(f"Touche inconnue : « {text} ».")


def key_label(name: str) -> str:
    """Libellé français d'une touche ou d'un bouton de souris."""
    if name in SPECIAL_KEYS:
        return SPECIAL_KEYS[name]
    if name in NUMPAD_KEYS:
        return NUMPAD_KEYS[name]
    if name in MOUSE_HOTKEYS:
        return MOUSE_HOTKEYS[name]
    if name.startswith("vk:"):
        return f"Code {name[3:]}"
    if len(name) == 1:
        return name.upper() if name.isalpha() else name
    return name


def is_modifier(name: str) -> bool:
    return name in MODIFIER_OF


@dataclass(frozen=True)
class Hotkey:
    """Raccourci : ensemble de modificateurs génériques + touche principale."""

    mods: FrozenSet[str]
    key: str

    def __str__(self) -> str:
        return "+".join([m for m in MODIFIER_ORDER if m in self.mods] + [self.key])

    @property
    def is_mouse(self) -> bool:
        return self.key in MOUSE_HOTKEYS

    def label(self) -> str:
        parts = [MODIFIER_LABELS[m] for m in MODIFIER_ORDER if m in self.mods]
        return "+".join(parts + [key_label(self.key)])


def parse_hotkey(text: str) -> Hotkey:
    """Analyse un raccourci du type ``"Ctrl+Maj+F6"``. Lève ``ValueError``."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("Raccourci vide.")
    if raw == "+":
        tokens = ["+"]
    elif raw.endswith("++"):
        tokens = raw[:-2].split("+") + ["+"] if raw[:-2] else ["+"]
    else:
        tokens = raw.split("+")
    tokens = [t.strip() for t in tokens]
    if any(not t for t in tokens):
        raise ValueError(f"Raccourci invalide : « {text} ».")
    *mod_tokens, main = tokens
    mods = set()
    for token in mod_tokens:
        name = normalize_key(token)
        if name not in MODIFIER_OF:
            raise ValueError(f"« {token} » n'est pas un modificateur (Ctrl, Alt, Maj, Win).")
        mods.add(MODIFIER_OF[name])
    low = main.lower()
    if low in MOUSE_HOTKEYS:
        key = low
    else:
        label_match = [n for n, lbl in MOUSE_HOTKEYS.items() if lbl.lower() == low]
        if label_match:
            key = label_match[0]
        else:
            key = normalize_key(main)
    if key in MODIFIER_OF:
        raise ValueError("Un raccourci doit se terminer par une touche autre qu'un modificateur.")
    return Hotkey(frozenset(mods), key)


def hotkey_label(text: str) -> str:
    """Libellé lisible d'un raccourci stocké (``""`` -> ``"Aucun"``)."""
    if not text:
        return "Aucun"
    try:
        return parse_hotkey(text).label()
    except ValueError:
        return text


def split_pynput_key(key) -> Tuple[Optional[str], Optional[str], Optional[int]]:
    """(nom spécial, caractère, code virtuel) d'une touche reçue de pynput.

    Fonctionne par introspection pour ne pas avoir à importer pynput.
    """
    if key is None:
        return None, None, None
    if hasattr(key, "char"):  # KeyCode
        return None, key.char, getattr(key, "vk", None)
    return getattr(key, "name", None), None, None  # membre de l'énumération Key


def hotkey_name_from_event(
    special: Optional[str],
    char: Optional[str],
    vk: Optional[int],
    platform: str = PLATFORM,
) -> Optional[str]:
    """Nom normalisé, pour la détection des raccourcis, d'une touche reçue.

    ``special`` est le nom d'un membre de ``pynput.keyboard.Key`` ; ``char`` et
    ``vk`` viennent d'un ``KeyCode``. Les modificateurs sont ramenés à leur
    forme générique et les lettres en minuscules. Sous Windows, le code
    virtuel prime pour les lettres et les chiffres : Ctrl+A y produit le
    caractère de contrôle ``"\\x01"``.
    """
    if special:
        return MODIFIER_OF.get(special, special)
    pad = numpad_name(vk, platform)
    if pad:
        return pad
    if platform == "win32" and vk is not None:
        if 0x41 <= vk <= 0x5A:
            return chr(vk).lower()
        if 0x30 <= vk <= 0x39:
            return chr(vk)
    if char and char.isprintable():
        return "space" if char == " " else char.lower()
    if vk is not None:
        return f"vk:{vk}"
    return None


def record_key_from_event(
    special: Optional[str],
    char: Optional[str],
    vk: Optional[int],
    platform: str = PLATFORM,
) -> Optional[KeyRef]:
    """Touche à enregistrer dans une macro à partir d'un événement clavier."""
    if special:
        return KeyRef(special)
    pad = numpad_name(vk, platform)
    if pad:
        return KeyRef(pad)
    hint = vk if platform == "win32" else None
    if char and char.isprintable():
        if char == " ":
            return KeyRef("space")
        return KeyRef(char.lower() if char.isalpha() else char, hint)
    if platform == "win32" and vk is not None:
        if 0x41 <= vk <= 0x5A:
            return KeyRef(chr(vk).lower(), vk)
        if 0x30 <= vk <= 0x39:
            return KeyRef(chr(vk), vk)
    if vk is not None:
        return KeyRef(f"vk:{vk}")
    return None


def hotkey_name_of_ref(ref: KeyRef) -> str:
    """Nom, tel que vu par la détection des raccourcis, d'une touche envoyée."""
    name = ref.name
    if name in MODIFIER_OF:
        return MODIFIER_OF[name]
    if len(name) == 1:
        return name.lower()
    return name
