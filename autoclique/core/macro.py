"""Macro : liste d'actions, options de lecture et format de fichier JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .actions import Action

FILE_FORMAT = "autoclique-macro"
FILE_VERSION = 1


@dataclass
class Macro:
    name: str = "Nouvelle macro"
    actions: List[Action] = field(default_factory=list)
    hotkey: str = ""
    repeat: int = 1  # 0 = indéfiniment
    speed: float = 1.0
    loop_delay: int = 0  # ms entre deux répétitions
    humanize: int = 0  # variation aléatoire des délais, en %
    description: str = ""

    def copy(self) -> "Macro":
        return Macro.from_dict(self.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": FILE_FORMAT,
            "version": FILE_VERSION,
            "name": self.name,
            "description": self.description,
            "hotkey": self.hotkey,
            "repeat": self.repeat,
            "speed": self.speed,
            "loop_delay": self.loop_delay,
            "humanize": self.humanize,
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Macro":
        if not isinstance(data, dict):
            raise ValueError("Le fichier ne contient pas une macro.")
        fmt = data.get("format", FILE_FORMAT)
        if fmt != FILE_FORMAT:
            raise ValueError("Ce fichier n'est pas une macro Autoclique.")
        actions_data = data.get("actions", [])
        if not isinstance(actions_data, list):
            raise ValueError("Liste d'actions invalide.")
        actions = []
        for index, item in enumerate(actions_data, start=1):
            try:
                actions.append(Action.from_dict(item))
            except ValueError as exc:
                raise ValueError(f"Étape {index} : {exc}") from None
        return cls(
            name=str(data.get("name") or "Macro sans nom").strip() or "Macro sans nom",
            actions=actions,
            hotkey=str(data.get("hotkey") or ""),
            repeat=_int(data.get("repeat"), 1, 0, 10_000_000),
            speed=_float(data.get("speed"), 1.0, 0.05, 100.0),
            loop_delay=_int(data.get("loop_delay"), 0, 0, 86_400_000),
            humanize=_int(data.get("humanize"), 0, 0, 90),
            description=str(data.get("description") or ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "Macro":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Fichier JSON invalide : {exc}") from None
        return cls.from_dict(data)


def _int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float, lo: float, hi: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


# --- Analyse des blocs -----------------------------------------------------------


@dataclass
class BlockInfo:
    """Résultat de l'analyse de la structure d'une liste d'actions.

    ``match`` relie les actions de structure entre elles :

    * début de boucle -> fin de boucle, et fin de boucle -> début ;
    * condition -> « Sinon » s'il existe, sinon -> « Fin si » ;
    * « Sinon » -> « Fin si » ;
    * « Sortir de la boucle » -> fin de la boucle englobante.

    ``depth`` donne le niveau d'indentation de chaque action et ``errors``
    la liste des problèmes (indice de l'action, message).
    """

    match: Dict[int, int] = field(default_factory=dict)
    depth: List[int] = field(default_factory=list)
    errors: List[Tuple[int, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def error_text(self, limit: int = 5) -> str:
        lines = [f"Étape {index + 1} : {message}" for index, message in self.errors[:limit]]
        if len(self.errors) > limit:
            lines.append(f"… et {len(self.errors) - limit} autre(s) problème(s).")
        return "\n".join(lines)


def analyze(actions: List[Action]) -> BlockInfo:
    info = BlockInfo(depth=[0] * len(actions))
    # Pile de blocs ouverts : [genre, indice, indice du « Sinon », sorties]
    stack: List[list] = []
    for i, action in enumerate(actions):
        role = action.spec.block if action.enabled else ""
        info.depth[i] = len(stack)
        if role == "open_loop":
            stack.append(["loop", i, None, []])
        elif role == "open_if":
            stack.append(["if", i, None, []])
        elif role == "else":
            if stack and stack[-1][0] == "if" and stack[-1][2] is None:
                stack[-1][2] = i
                info.depth[i] = len(stack) - 1
            elif stack and stack[-1][0] == "if":
                info.errors.append((i, "« Sinon » en double dans le même bloc « Si »."))
            else:
                info.errors.append((i, "« Sinon » sans condition « Si » correspondante."))
        elif role == "close_loop":
            if stack and stack[-1][0] == "loop":
                _kind, start, _else, breaks = stack.pop()
                info.match[start] = i
                info.match[i] = start
                for b in breaks:
                    info.match[b] = i
                info.depth[i] = len(stack)
            elif stack:
                info.errors.append((i, f"le bloc « Si » de l'étape {stack[-1][1] + 1} doit être "
                                       "fermé (« Fin si ») avant cette « Fin de répétition »."))
            else:
                info.errors.append((i, "« Fin de répétition » sans « Répéter » correspondant."))
        elif role == "close_if":
            if stack and stack[-1][0] == "if":
                _kind, start, else_index, _breaks = stack.pop()
                if else_index is not None:
                    info.match[start] = else_index
                    info.match[else_index] = i
                else:
                    info.match[start] = i
                info.depth[i] = len(stack)
            elif stack:
                info.errors.append((i, f"la boucle « Répéter » de l'étape {stack[-1][1] + 1} doit "
                                       "être fermée avant ce « Fin si »."))
            else:
                info.errors.append((i, "« Fin si » sans condition « Si » correspondante."))
        elif role == "break":
            loops = [entry for entry in stack if entry[0] == "loop"]
            if loops:
                loops[-1][3].append(i)
            else:
                info.errors.append((i, "« Sortir de la boucle » en dehors d'une boucle."))
    for kind, start, _else, _breaks in stack:
        label = "« Répéter »" if kind == "loop" else "« Si »"
        closer = "« Fin de répétition »" if kind == "loop" else "« Fin si »"
        info.errors.append((start, f"{label} n'est pas fermé (ajoutez {closer})."))
    info.errors.sort()
    return info


@dataclass
class DurationEstimate:
    seconds: float = 0.0
    variable: bool = False  # attentes d'image, conditions, sous-macros…
    infinite: bool = False  # boucle sans fin


def estimate_duration(actions: List[Action]) -> DurationEstimate:
    """Durée approximative d'une exécution de la liste d'actions."""
    info = analyze(actions)
    if not info.ok:
        return DurationEstimate(variable=True)
    result = DurationEstimate()

    def span(start: int, end: int) -> float:
        total = 0.0
        i = start
        while i < end:
            action = actions[i]
            if not action.enabled:
                i += 1
                continue
            p = action.params
            if action.spec.has_delay:
                total += action.delay / 1000.0
            kind = action.type
            if kind == "loop_start":
                close = info.match[i]
                body = span(i + 1, close)
                count = int(p.get("count", 0))
                if count <= 0:
                    result.infinite = True
                else:
                    total += body * count
                i = close + 1
                continue
            if kind in ("if_image", "if_pixel"):
                result.variable = True
                target = info.match[i]
                if actions[target].spec.block == "else":
                    end_if = info.match[target]
                    total += max(span(i + 1, target), span(target + 1, end_if))
                    i = end_if + 1
                else:
                    total += span(i + 1, target)
                    i = target + 1
                continue
            if kind == "wait":
                total += p.get("duration", 0) / 1000.0
                if p.get("random"):
                    result.variable = True
            elif kind == "click":
                total += p.get("hold", 0) * p.get("count", 1) / 1000.0
            elif kind == "key_press":
                total += p.get("hold", 0) / 1000.0
            elif kind == "move":
                total += p.get("duration", 0) / 1000.0
            elif kind == "type_text":
                total += max(0, len(p.get("text", "")) - 1) * p.get("interval", 0) / 1000.0
            elif kind in ("wait_pixel", "wait_image", "click_image", "focus_window", "run_macro",
                          "break", "stop"):
                result.variable = True
            i += 1
        return total

    result.seconds = span(0, len(actions))
    return result


def find_block_end(actions: List[Action], index: int) -> Optional[int]:
    """Indice de l'action qui ferme le bloc ouvert en ``index`` (ou ``None``)."""
    info = analyze(actions)
    role = actions[index].spec.block
    if role == "open_loop":
        return info.match.get(index)
    if role == "open_if":
        target = info.match.get(index)
        if target is not None and actions[target].spec.block == "else":
            return info.match.get(target)
        return target
    return None
