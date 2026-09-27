"""Stockage : dossier de données, paramètres et bibliothèque de macros.

Chaque macro est un fichier JSON du dossier ``macros``. Les images utilisées
par la reconnaissance d'écran sont intégrées aux fichiers (PNG en base64) :
une macro exportée se partage donc en un seul fichier.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .macro import Macro
from .settings import Settings

log = logging.getLogger("autoclique")

APP_FOLDER = "Autoclique IA"


def data_dir() -> Path:
    """Dossier des données de l'utilisateur (``AUTOCLIQUE_HOME`` le remplace)."""
    override = os.environ.get("AUTOCLIQUE_HOME")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / APP_FOLDER
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_FOLDER
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autoclique-ia"


def write_text_atomic(path: Path, text: str) -> None:
    """Écrit un fichier sans risque de le laisser à moitié écrit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def setup_logging(folder: Optional[Path] = None, level: int = logging.INFO) -> Optional[Path]:
    """Journal dans ``autoclique.log`` (fichier tournant, 1 Mo × 3)."""
    logger = logging.getLogger("autoclique")
    logger.setLevel(level)
    folder = folder or data_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "autoclique.log"
        if not any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
            handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3,
                                                           encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        return path
    except OSError:
        return None


# --- Paramètres ------------------------------------------------------------------------


def settings_path(folder: Optional[Path] = None) -> Path:
    return (folder or data_dir()) / "settings.json"


def load_settings(path: Optional[Path] = None) -> Settings:
    path = path or settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Settings()
    except OSError as exc:
        log.warning("Lecture des paramètres impossible : %s", exc)
        return Settings()
    try:
        return Settings.from_dict(json.loads(text))
    except (ValueError, TypeError) as exc:
        backup = path.with_suffix(".json.bak")
        log.warning("Paramètres illisibles (%s), copie dans %s", exc, backup.name)
        try:
            path.replace(backup)
        except OSError:
            pass
        return Settings()


def save_settings(settings: Settings, path: Optional[Path] = None) -> None:
    write_text_atomic(path or settings_path(), json.dumps(settings.to_dict(), ensure_ascii=False, indent=2))


# --- Bibliothèque de macros ---------------------------------------------------------------

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
MAX_NAME_LENGTH = 100


def safe_filename(name: str) -> str:
    base = _INVALID_CHARS.sub("_", name).strip().strip(".") or "macro"
    base = base[:80].rstrip()
    if base.lower() in _RESERVED:
        base = "_" + base
    return base


def validate_name(name: str) -> str:
    """Nom de macro nettoyé ; lève ``ValueError`` s'il est inutilisable."""
    cleaned = " ".join((name or "").split())
    if not cleaned:
        raise ValueError("Le nom de la macro ne peut pas être vide.")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValueError(f"Le nom ne doit pas dépasser {MAX_NAME_LENGTH} caractères.")
    return cleaned


class MacroLibrary:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._paths: Dict[str, Path] = {}
        self._cache: Dict[str, Tuple[float, Macro]] = {}
        self.errors: List[str] = []
        self.refresh()

    def refresh(self) -> None:
        """Relit la liste des macros présentes dans le dossier."""
        self._paths.clear()
        self.errors = []
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            files = sorted(self.folder.glob("*.json"))
        except OSError as exc:
            self.errors.append(f"Dossier des macros inaccessible : {exc}")
            return
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                name = validate_name(str(data.get("name") or path.stem))
            except (OSError, ValueError, AttributeError) as exc:
                self.errors.append(f"{path.name} : {exc}")
                continue
            if self._find(name) is not None:
                name = self._unique_in_index(name)
            self._paths[name] = path

    def _find(self, name: str) -> Optional[str]:
        folded = name.casefold()
        for existing in self._paths:
            if existing.casefold() == folded:
                return existing
        return None

    def _unique_in_index(self, base: str) -> str:
        n = 2
        while self._find(f"{base} ({n})") is not None:
            n += 1
        return f"{base} ({n})"

    def names(self) -> List[str]:
        return sorted(self._paths, key=str.casefold)

    def exists(self, name: str) -> bool:
        return self._find(name) is not None

    def unique_name(self, base: str) -> str:
        base = validate_name(base)
        return base if not self.exists(base) else self._unique_in_index(base)

    def path_of(self, name: str) -> Optional[Path]:
        found = self._find(name)
        return self._paths.get(found) if found is not None else None

    def load(self, name: str) -> Macro:
        found = self._find(name)
        if found is None:
            raise KeyError(f"Macro introuvable : « {name} ».")
        path = self._paths[found]
        try:
            mtime = path.stat().st_mtime
        except OSError as exc:
            raise KeyError(f"Macro introuvable : « {name} » ({exc}).") from None
        cached = self._cache.get(found)
        if cached is not None and cached[0] == mtime:
            return cached[1].copy()
        macro = Macro.from_json(path.read_text(encoding="utf-8"))
        macro.name = found
        self._cache[found] = (mtime, macro)
        return macro.copy()

    def get(self, name: str) -> Optional[Macro]:
        """Comme :meth:`load`, mais renvoie ``None`` si la macro n'existe pas."""
        try:
            return self.load(name)
        except (KeyError, ValueError, OSError):
            return None

    def _new_path(self, name: str, keep: Optional[Path] = None) -> Path:
        stem = safe_filename(name)
        candidate = self.folder / f"{stem}.json"
        n = 2
        taken = {p.resolve() for p in self._paths.values() if keep is None or p != keep}
        while candidate.resolve() in taken or (candidate.exists() and candidate != keep):
            candidate = self.folder / f"{stem} ({n}).json"
            n += 1
        return candidate

    def save(self, macro: Macro, previous_name: Optional[str] = None) -> Path:
        """Enregistre ``macro`` ; ``previous_name`` permet de la renommer."""
        macro.name = validate_name(macro.name)
        old_key = self._find(previous_name) if previous_name else None
        clash = self._find(macro.name)
        if clash is not None and clash != old_key:
            raise ValueError(f"Une macro nommée « {clash} » existe déjà.")
        old_path = self._paths.pop(old_key) if old_key is not None else None
        if old_key is not None:
            self._cache.pop(old_key, None)
        if old_path is not None and safe_filename(macro.name) == safe_filename(old_key or ""):
            path = old_path
        else:
            path = self._new_path(macro.name)
        write_text_atomic(path, macro.to_json())
        if old_path is not None and old_path != path:
            try:
                old_path.unlink()
            except OSError as exc:
                log.warning("Suppression de l'ancien fichier impossible : %s", exc)
        self._paths[macro.name] = path
        return path

    def delete(self, name: str) -> None:
        found = self._find(name)
        if found is None:
            return
        path = self._paths.pop(found)
        self._cache.pop(found, None)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def import_file(self, source: Path) -> Macro:
        """Copie un fichier de macro dans la bibliothèque (renommée si besoin)."""
        macro = Macro.from_json(Path(source).read_text(encoding="utf-8"))
        macro.name = self.unique_name(macro.name)
        self.save(macro)
        return macro

    def export(self, name: str, destination: Path) -> None:
        write_text_atomic(Path(destination), self.load(name).to_json())

    def hotkeys(self) -> Dict[str, str]:
        """Raccourcis propres à chaque macro (``{nom: raccourci}``)."""
        result = {}
        for name in self.names():
            macro = self.get(name)
            if macro is not None and macro.hotkey:
                result[name] = macro.hotkey
        return result
