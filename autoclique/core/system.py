"""Fonctions dépendantes du système : ouvrir un programme, activer une fenêtre."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import webbrowser
from typing import List

WINDOWS = sys.platform.startswith("win")
MACOS = sys.platform == "darwin"

_URL = re.compile(r"^[a-z][a-z0-9+.-]*://|^mailto:", re.IGNORECASE)


def open_target(target: str, args: str = "") -> None:
    """Ouvre un site web, un fichier, un dossier ou lance un programme."""
    target = (target or "").strip()
    if not target:
        raise ValueError("Aucun programme, fichier ou adresse indiqué.")
    if _URL.match(target):
        webbrowser.open(target)
        return
    target = os.path.expandvars(os.path.expanduser(target))
    args = (args or "").strip()
    if args:
        if WINDOWS:
            subprocess.Popen(f'"{target}" {args}')
        else:
            subprocess.Popen([target] + shlex.split(args), start_new_session=True)
        return
    if WINDOWS:
        os.startfile(target)  # type: ignore[attr-defined]
    elif MACOS:
        subprocess.Popen(["open", target])
    elif os.access(target, os.X_OK) and not os.path.isdir(target):
        subprocess.Popen([target], start_new_session=True)
    else:
        subprocess.Popen(["xdg-open", target], start_new_session=True)


def open_folder(path: str) -> None:
    """Ouvre un dossier dans l'explorateur de fichiers."""
    if WINDOWS:
        os.startfile(path)  # type: ignore[attr-defined]
    elif MACOS:
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path], start_new_session=True)


# --- Fenêtres -------------------------------------------------------------------------


_user32 = None


def _win_user32():
    """user32 avec des prototypes explicites (poignées 64 bits)."""
    global _user32
    if _user32 is None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = wintypes.HWND
        user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
        user32.IsWindowVisible.argtypes = [hwnd]
        user32.GetWindowTextLengthW.argtypes = [hwnd]
        user32.GetWindowTextW.argtypes = [hwnd, wintypes.LPWSTR, ctypes.c_int]
        user32.IsIconic.argtypes = [hwnd]
        user32.ShowWindow.argtypes = [hwnd, ctypes.c_int]
        user32.SetForegroundWindow.argtypes = [hwnd]
        user32.BringWindowToTop.argtypes = [hwnd]
        user32.GetForegroundWindow.restype = hwnd
        user32.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        _user32 = user32
    return _user32


def _win_windows() -> List[tuple]:
    import ctypes
    from ctypes import wintypes

    user32 = _win_user32()
    result = []
    proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        if hwnd and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                if buffer.value.strip():
                    result.append((hwnd, buffer.value))
        return True

    callback_ref = proc_type(callback)  # garder une référence pendant l'appel
    user32.EnumWindows(ctypes.cast(callback_ref, ctypes.c_void_p), 0)
    return result


def _win_activate(hwnd) -> bool:
    import ctypes

    user32 = _win_user32()
    kernel32 = ctypes.windll.kernel32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() == hwnd:
        return True
    # Windows limite le changement de premier plan : on s'attache
    # temporairement à la file d'entrée de la fenêtre active.
    foreground = user32.GetForegroundWindow()
    fg_thread = user32.GetWindowThreadProcessId(foreground, None)
    our_thread = kernel32.GetCurrentThreadId()
    attached = fg_thread and fg_thread != our_thread and user32.AttachThreadInput(our_thread, fg_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(our_thread, fg_thread, False)
    if user32.GetForegroundWindow() == hwnd:
        return True
    # Dernier recours : un appui sur Alt débloque SetForegroundWindow.
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    return user32.GetForegroundWindow() == hwnd


def list_window_titles() -> List[str]:
    """Titres des fenêtres visibles (liste vide si non pris en charge)."""
    try:
        if WINDOWS:
            titles = [title for _hwnd, title in _win_windows()]
        elif MACOS:
            script = ('tell application "System Events" to get name of every process '
                      'whose background only is false')
            out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=5)
            titles = [t.strip() for t in out.stdout.split(",") if t.strip()]
        elif shutil.which("wmctrl"):
            out = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=5)
            titles = [line.split(None, 3)[3] for line in out.stdout.splitlines() if len(line.split(None, 3)) == 4]
        else:
            titles = []
    except Exception:
        return []
    seen, unique = set(), []
    for title in titles:
        if title not in seen:
            seen.add(title)
            unique.append(title)
    return unique


def focus_window(title: str) -> bool:
    """Met au premier plan la première fenêtre dont le titre contient ``title``.

    Sous macOS, ``title`` est le nom de l'application. Renvoie ``False`` si
    aucune fenêtre ne correspond (ou si le système n'est pas pris en charge).
    """
    needle = (title or "").strip()
    if not needle:
        raise ValueError("Aucun titre de fenêtre indiqué.")
    if WINDOWS:
        low = needle.lower()
        for hwnd, text in _win_windows():
            if low in text.lower():
                return _win_activate(hwnd)
        return False
    if MACOS:
        script = f'tell application "{needle.replace(chr(34), "")}" to activate'
        return subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10).returncode == 0
    if shutil.which("wmctrl"):
        return subprocess.run(["wmctrl", "-a", needle], capture_output=True, timeout=10).returncode == 0
    if shutil.which("xdotool"):
        out = subprocess.run(["xdotool", "search", "--name", re.escape(needle), "windowactivate"],
                             capture_output=True, timeout=10)
        return out.returncode == 0
    raise RuntimeError("Installez « wmctrl » ou « xdotool » pour activer des fenêtres sous Linux.")


def set_dpi_awareness() -> None:
    """Rend le processus « DPI aware » sous Windows.

    Sans cela, avec une mise à l'échelle de l'affichage supérieure à 100 %,
    les coordonnées lues et envoyées ne correspondent pas aux pixels réels.
    """
    if not WINDOWS:
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
