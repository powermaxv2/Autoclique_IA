"""Construit l'exécutable autonome d'Autoclique IA avec PyInstaller.

Usage :
    pip install -r requirements.txt pyinstaller
    python tools/build_exe.py            # un seul fichier (dist/AutocliqueIA.exe sous Windows)
    python tools/build_exe.py --onedir   # un dossier (démarrage plus rapide)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "AutocliqueIA"

# pynput choisit son implémentation au démarrage : PyInstaller ne la détecte pas seul.
HIDDEN_IMPORTS = {
    "win32": ["pynput.keyboard._win32", "pynput.mouse._win32"],
    "darwin": ["pynput.keyboard._darwin", "pynput.mouse._darwin"],
    "linux": ["pynput.keyboard._xorg", "pynput.mouse._xorg"],
}


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def build(onedir: bool = False) -> Path:
    key = platform_key()
    assets = ROOT / "autoclique" / "assets"
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", NAME,
        "--windowed",
        "--onedir" if onedir else "--onefile",
        "--add-data", f"{assets}{os.pathsep}autoclique/assets",
        "--collect-data", "sv_ttk",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if key == "win32":
        command += ["--icon", str(assets / "icon.ico")]
    for module in HIDDEN_IMPORTS[key]:
        command += ["--hidden-import", module]
    command.append(str(ROOT / "launcher.py"))
    print(" ".join(command))
    subprocess.check_call(command, cwd=ROOT)
    suffix = ".exe" if key == "win32" else (".app" if key == "darwin" else "")
    target = ROOT / "dist" / (NAME if onedir else NAME + suffix)
    print(f"\nExécutable prêt : {target}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--onedir", action="store_true", help="produire un dossier au lieu d'un fichier unique")
    args = parser.parse_args()
    build(args.onedir)


if __name__ == "__main__":
    main()
