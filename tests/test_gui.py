"""Tests de l'interface graphique (nécessitent un affichage, par ex. Xvfb).

La souris et le clavier sont remplacés par un :class:`FakeBackend` : les tests
ne déplacent jamais le vrai curseur.
"""

import os
import sys
import time

import pytest

tk = pytest.importorskip("tkinter")

if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
    pytest.skip("aucun affichage disponible", allow_module_level=True)

from autoclique.core.actions import Action  # noqa: E402
from autoclique.core.backend import FakeBackend  # noqa: E402
from autoclique.core.macro import Macro  # noqa: E402


def pump(root, until=None, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until is not None else True


@pytest.fixture
def app(tmp_path):
    from autoclique.gui.main_window import App

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk indisponible : {exc}")
    root.withdraw()
    application = App(root, data_folder=tmp_path, backend=FakeBackend(position=(500, 500)),
                      enable_input=False)
    application.settings.minimize_on_run = False
    yield application
    if not application._closing:
        application.close()


def new_macro(app, name, actions, **fields):
    macro = Macro(name, actions, **fields)
    app.library.save(macro)
    app.macros_tab.refresh_library(select=name)
    return macro


def test_first_run_creates_example(app):
    assert app.library.names() == ["Exemple — 10 clics"]
    assert len(app.macros_tab.macro.actions) == 5
    assert len(app.macros_tab.tree.get_children()) == 5
    assert "5 actions" in app.macros_tab.info_label.cget("text")


def test_play_macro_with_fake_backend(app):
    new_macro(app, "Rapide", [Action.new("click", pos=[5, 6]), Action.new("key_press", key="a", hold=0)],
              repeat=3)
    app.play_current()
    assert app.task_kind == "macro"
    assert pump(app.root, lambda: app.task is None)
    events = app.backend.events
    assert events.count(("click", "left", 1)) == 3
    assert "terminée" in app.status_text.cget("text")


def test_macro_error_selects_step(app):
    new_macro(app, "Erreur", [Action.new("wait", duration=1), Action.new("run_macro", macro="Absente")])
    app.play_current()
    assert pump(app.root, lambda: app.task is None)
    assert "introuvable" in app.status_text.cget("text")
    assert app.macros_tab.tree.selection() == ("1",)


def test_invalid_structure_is_refused(app, monkeypatch):
    shown = []
    monkeypatch.setattr("autoclique.gui.main_window.messagebox.showerror", lambda *a, **k: shown.append(a))
    new_macro(app, "Invalide", [Action.new("loop_start")])
    app.play_current()
    assert app.task is None
    assert shown and "n'est pas fermé" in shown[0][1]


def test_clicker_count(app):
    tab = app.clicker_tab
    tab.millis.set("1")
    tab.repeat.set("count")
    tab.count.set("7")
    tab.position.set("fixed")
    tab.x.set("12")
    tab.y.set("34")
    app.start_clicker()
    assert app.task_kind == "clicker"
    assert pump(app.root, lambda: app.task is None)
    assert app.backend.events.count(("click", "left", 1)) == 7
    assert ("move", 12, 34) in app.backend.events
    assert "7 clic(s)" in app.status_text.cget("text")
    assert app.settings.clicker.count == 7  # configuration mémorisée


def test_clicker_invalid_key(app, monkeypatch):
    errors = []
    monkeypatch.setattr("autoclique.gui.main_window.messagebox.showerror", lambda *a, **k: errors.append(a))
    app.clicker_tab.mode.set("key")
    app.clicker_tab.key.set("touche inconnue")
    app.start_clicker()
    assert app.task is None
    assert errors


def test_hotkeys_toggle_and_stop(app):
    app.clicker_tab.millis.set("5")
    app.clicker_tab.repeat.set("infinite")
    app._hotkey_action("clicker", "press")
    assert app.task_kind == "clicker"
    pump(app.root, timeout=0.2)
    app._hotkey_action("stop_all", "press")
    assert pump(app.root, lambda: app.task is None)
    assert "arrêté" in app.status_text.cget("text")


def test_hold_mode(app):
    app.clicker_tab.millis.set("5")
    app.clicker_tab.repeat.set("infinite")
    app.clicker_tab.hotkey_mode.set("hold")
    app._hotkey_action("clicker", "press")
    assert app.task_kind == "clicker"
    pump(app.root, timeout=0.1)
    app._hotkey_action("clicker", "release")
    assert pump(app.root, lambda: app.task is None)


def test_busy_refuses_second_task(app):
    app.clicker_tab.millis.set("5")
    app.start_clicker()
    app.play_current()
    assert app.task_kind == "clicker"
    assert "déjà en cours" in app.status_text.cget("text")
    app.stop_all()
    assert pump(app.root, lambda: app.task is None)


def test_action_dialog_collects_values(app):
    from autoclique.gui.action_dialog import ActionDialog

    dialog = ActionDialog(app, app.root, Action.new("click"), is_new=True)
    editors = dialog.editors
    editors["button"].var.set("Droit")
    editors["count"].var.set("Double")
    editors["pos"].current.set(False)
    editors["pos"].x.set("100")
    editors["pos"].y.set("-20")
    editors["hold"].var.set("250")
    dialog.delay.set("75")
    dialog._ok()
    result = dialog.result
    assert result.params == {"button": "right", "count": 2, "pos": [100, -20], "hold": 250}
    assert result.delay == 75


def test_action_dialog_validation(app, monkeypatch):
    from autoclique.gui.action_dialog import ActionDialog

    errors = []
    monkeypatch.setattr("autoclique.gui.action_dialog.messagebox.showerror", lambda *a, **k: errors.append(a))
    dialog = ActionDialog(app, app.root, Action.new("key_press"))
    dialog.editors["key"].var.set("pas une touche")
    dialog._ok()
    assert dialog.result is None and errors
    dialog.editors["key"].var.set("Entrée")
    dialog._ok()
    assert dialog.result.params["key"] == "enter"


@pytest.mark.parametrize("type_id", ["click", "move", "scroll", "key_press", "hotkey", "type_text", "wait",
                                     "wait_pixel", "wait_image", "click_image", "if_image", "if_pixel",
                                     "loop_start", "run_macro", "comment", "open", "focus_window"])
def test_every_action_dialog_builds(app, type_id):
    from autoclique.gui.action_dialog import ActionDialog

    dialog = ActionDialog(app, app.root, Action.new(type_id))
    dialog.update_idletasks()
    dialog.destroy()


def test_add_block_wraps_selection(app, monkeypatch):
    new_macro(app, "Bloc", [Action.new("click"), Action.new("wait"), Action.new("key_press", key="a")])
    tab = app.macros_tab
    monkeypatch.setattr("autoclique.gui.macro_tab.edit_action", lambda _app, _p, action, **_k: action)
    tab.tree.selection_set(("0", "1"))
    tab.add_action("loop_start")
    types = [a.type for a in tab.macro.actions]
    assert types == ["loop_start", "click", "wait", "loop_end", "key_press"]
    tab.undo()
    assert [a.type for a in tab.macro.actions] == ["click", "wait", "key_press"]
    tab.redo()
    assert len(tab.macro.actions) == 5


def test_edit_operations_and_autosave(app):
    new_macro(app, "Édition", [Action.new("click"), Action.new("wait"), Action.new("key_press", key="a")])
    tab = app.macros_tab
    tab.tree.selection_set(("2",))
    tab.move_selected(-1)
    assert [a.type for a in tab.macro.actions] == ["click", "key_press", "wait"]
    tab.duplicate_selected()
    assert [a.type for a in tab.macro.actions] == ["click", "key_press", "key_press", "wait"]
    tab.toggle_enabled()
    assert tab.macro.actions[2].enabled is False
    tab.tree.selection_set(("0",))
    tab.copy_selected()
    tab.tree.selection_set(("3",))
    tab.paste()
    assert [a.type for a in tab.macro.actions][-1] == "click"
    tab.delete_selected()
    assert len(tab.macro.actions) == 4
    tab.flush_save()
    saved = app.library.load("Édition")
    assert [a.type for a in saved.actions] == ["click", "key_press", "key_press", "wait"]
    assert saved.actions[2].enabled is False


def test_playback_options_saved(app):
    new_macro(app, "Options", [Action.new("click")])
    tab = app.macros_tab
    tab.repeat.set("0")
    tab.speed.set("2,5")
    tab.humanize.set("12")
    tab.flush_save()
    saved = app.library.load("Options")
    assert (saved.repeat, saved.speed, saved.humanize) == (0, 2.5, 12)
    assert "sans fin" in tab.info_label.cget("text")


def test_rename_updates_run_macro_references(app, monkeypatch):
    new_macro(app, "Appelée", [Action.new("click")])
    new_macro(app, "Appelante", [Action.new("run_macro", macro="Appelée")])
    tab = app.macros_tab
    tab.lib_tree.selection_set("Appelée")
    pump(app.root, timeout=0.1)
    monkeypatch.setattr("autoclique.gui.macro_tab.ask_text", lambda *a, **k: "Renommée")
    tab.rename_macro()
    assert "Renommée" in app.library.names()
    assert app.library.load("Appelante").actions[0].params["macro"] == "Renommée"


def test_receive_recording_creates_macro(app):
    from autoclique.core.recorder import RecordOptions

    actions = [Action.new("click", pos=[1, 1]), Action.new("key_press", key="b")]
    app.macros_tab.receive_recording(actions, RecordOptions(destination="new"))
    name = app.macros_tab.macro_name
    assert name.startswith("Enregistrement du")
    assert len(app.library.load(name).actions) == 2
    app.macros_tab.receive_recording(actions, RecordOptions(destination="append"))
    app.macros_tab.flush_save()
    assert len(app.library.load(name).actions) == 4


def test_global_hotkey_conflict(app, monkeypatch):
    monkeypatch.setattr("autoclique.gui.main_window.messagebox.askyesno", lambda *a, **k: True)
    app.set_global_hotkey("play", "f6")  # déjà utilisé par l'auto-clic
    assert app.settings.hotkeys["play"] == "f6"
    assert app.settings.hotkeys["clicker"] == ""
    assert app.settings_tab.hotkey_labels["play"].cget("text") == "F6"
    assert app.settings_tab.hotkey_labels["clicker"].cget("text") == "Aucun"
    assert app.status_hint.cget("text") == "Raccourcis globaux indisponibles"  # pas d'écouteur ici


def test_theme_switch_and_settings_file(app, tmp_path):
    app.set_theme("light")
    app.save_settings_now()
    import json

    data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert data["theme"] == "light"


def test_screen_picker_point_and_region(app, monkeypatch):
    import numpy as np

    from autoclique.core.screen import Shot

    pixels = np.zeros((300, 400, 3), np.uint8)
    pixels[20, 10] = (255, 128, 0)
    monkeypatch.setattr(app.screen, "grab", lambda region=None: Shot(pixels, 0, 0, 1.0))
    results = []
    app.pick_point(results.append)
    assert pump(app.root, lambda: any(isinstance(w, tk.Toplevel) and w.winfo_viewable()
                                      for w in app.root.winfo_children()))
    overlay = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    canvas = overlay.winfo_children()[0]
    canvas.event_generate("<Motion>", x=10, y=20)
    canvas.event_generate("<ButtonPress-1>", x=10, y=20)
    assert pump(app.root, lambda: results)
    assert results[0] == (10, 20, (255, 128, 0))

    app.pick_region(results.append)
    assert pump(app.root, lambda: len([w for w in app.root.winfo_children()
                                       if isinstance(w, tk.Toplevel) and w.winfo_exists()]) >= 1)
    overlay = [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    canvas = overlay.winfo_children()[0]
    canvas.event_generate("<ButtonPress-1>", x=50, y=60)
    canvas.event_generate("<B1-Motion>", x=90, y=100)
    canvas.event_generate("<ButtonRelease-1>", x=90, y=100)
    assert pump(app.root, lambda: len(results) == 2)
    x, y, w, h, crop = results[1]
    assert (x, y, w, h) == (50, 60, 40, 40)
    assert crop.shape == (40, 40, 3)


def test_close_saves_everything(app, tmp_path):
    new_macro(app, "Fermeture", [Action.new("click")])
    app.macros_tab.tree.selection_set(("0",))
    app.macros_tab.delete_selected()
    app.close()
    assert app.library.load("Fermeture").actions == []
    assert (tmp_path / "settings.json").exists()
