"""Paramètres de l'application (sauvegardés dans ``settings.json``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from .clicker import ClickerConfig
from .recorder import RecordOptions

DEFAULT_HOTKEYS: Dict[str, str] = {
    "clicker": "f6",
    "record": "f8",
    "play": "f9",
    "stop_all": "esc",
}

HOTKEY_LABELS: Dict[str, str] = {
    "clicker": "Démarrer / arrêter l'auto-clic",
    "record": "Démarrer / arrêter l'enregistrement",
    "play": "Lire / arrêter la macro sélectionnée",
    "stop_all": "Arrêt d'urgence (tout arrêter)",
}


@dataclass
class Settings:
    hotkeys: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))
    theme: str = "dark"  # "dark" ou "light"
    minimize_on_run: bool = True
    always_on_top: bool = False
    failsafe: bool = True
    default_delay: int = 100  # ms, délai des nouvelles actions
    start_countdown: int = 0  # s, avant une lecture ou un enregistrement
    confirm_delete: bool = True
    clicker: ClickerConfig = field(default_factory=ClickerConfig)
    record: RecordOptions = field(default_factory=RecordOptions)
    last_macro: str = ""
    geometry: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hotkeys": dict(self.hotkeys),
            "theme": self.theme,
            "minimize_on_run": self.minimize_on_run,
            "always_on_top": self.always_on_top,
            "failsafe": self.failsafe,
            "default_delay": self.default_delay,
            "start_countdown": self.start_countdown,
            "confirm_delete": self.confirm_delete,
            "clicker": self.clicker.to_dict(),
            "record": self.record.to_dict(),
            "last_macro": self.last_macro,
            "geometry": self.geometry,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "Settings":
        settings = cls()
        if not isinstance(data, dict):
            return settings
        hotkeys = data.get("hotkeys")
        if isinstance(hotkeys, dict):
            for key in DEFAULT_HOTKEYS:
                if key in hotkeys and isinstance(hotkeys[key], str):
                    settings.hotkeys[key] = hotkeys[key]
        if data.get("theme") in ("dark", "light"):
            settings.theme = data["theme"]
        for name in ("minimize_on_run", "always_on_top", "failsafe", "confirm_delete"):
            if isinstance(data.get(name), bool):
                setattr(settings, name, data[name])
        for name, lo, hi in (("default_delay", 0, 60000), ("start_countdown", 0, 60)):
            try:
                setattr(settings, name, max(lo, min(hi, int(data.get(name, getattr(settings, name))))))
            except (TypeError, ValueError):
                pass
        settings.clicker = ClickerConfig.from_dict(data.get("clicker"))
        settings.record = RecordOptions.from_dict(data.get("record"))
        for name in ("last_macro", "geometry"):
            if isinstance(data.get(name), str):
                setattr(settings, name, data[name])
        return settings
