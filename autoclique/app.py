"""Point d'entrée de l'interface graphique."""

from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import List, Optional


def _prepare_process() -> None:
    from .core.system import set_dpi_awareness
    from .core.timing import enable_high_resolution_timer

    set_dpi_awareness()  # doit précéder la création de la fenêtre
    enable_high_resolution_timer()


def _create_root():
    import tkinter as tk

    root = tk.Tk(className="Autoclique")
    return root


def run_gui(data_folder: Optional[Path] = None) -> int:
    _prepare_process()
    from .gui.main_window import App

    root = _create_root()
    App(root, data_folder=data_folder)
    root.mainloop()
    return 0


def run_selftest() -> int:
    """Construit l'interface, parcourt les onglets puis se ferme (tests / CI)."""
    report = Path(tempfile.gettempdir()) / "autoclique-selftest.txt"
    try:
        _prepare_process()
        from .gui.main_window import App

        folder = Path(tempfile.mkdtemp(prefix="autoclique-selftest-"))
        root = _create_root()
        app = App(root, data_folder=folder)
        steps = []

        def visit(index: int = 0) -> None:
            tabs = app.notebook.tabs()
            if index < len(tabs):
                app.notebook.select(index)
                steps.append(app.notebook.tab(index, "text").strip())
                root.after(150, visit, index + 1)
            else:
                app.set_theme("light")
                app.set_theme("dark")
                root.after(200, app.close)

        root.after(300, visit)
        root.after(15000, root.destroy)  # garde-fou
        root.mainloop()
        report.write_text("OK : " + ", ".join(steps) + "\n", encoding="utf-8")
        print("Autotest réussi :", ", ".join(steps))
        return 0
    except Exception:
        details = traceback.format_exc()
        try:
            report.write_text(details, encoding="utf-8")
        except OSError:
            pass
        print(details, file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return run_selftest()
    folder = os.environ.get("AUTOCLIQUE_HOME")
    return run_gui(Path(folder) if folder else None)


if __name__ == "__main__":
    sys.exit(main())
