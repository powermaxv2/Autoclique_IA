"""Tests avec la vraie souris et le vrai clavier (pynput).

Ils déplacent le curseur et envoient des touches : ils ne s'exécutent que si
``AUTOCLIQUE_INTEGRATION=1`` (par exemple sous Xvfb en intégration continue).
"""

import os
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AUTOCLIQUE_INTEGRATION") != "1",
    reason="définir AUTOCLIQUE_INTEGRATION=1 pour piloter la vraie souris",
)


def wait_for(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_backend_moves_and_clicks():
    from autoclique.core.backend import PynputBackend

    backend = PynputBackend()
    backend.move_to(123, 234)
    assert wait_for(lambda: backend.position() == (123, 234))
    backend.mouse_down("left")
    assert backend.held()[0] == ["left"]
    backend.release_all()
    assert backend.held() == ([], [])


def test_recorder_and_player_roundtrip():
    from pynput import keyboard, mouse

    from autoclique.core.backend import FakeBackend
    from autoclique.core.macro import Macro
    from autoclique.core.player import MacroPlayer, PlaybackOptions
    from autoclique.core.recorder import MacroRecorder, RecordOptions

    recorder = MacroRecorder(RecordOptions(record_moves=False))
    recorder.start()
    try:
        m, k = mouse.Controller(), keyboard.Controller()
        m.position = (300, 200)
        time.sleep(0.05)
        m.click(mouse.Button.left)
        time.sleep(0.05)
        k.press("x")
        time.sleep(0.06)
        k.release("x")
        time.sleep(0.05)
        m.scroll(0, -2)
        assert wait_for(lambda: recorder.count >= 5)
    finally:
        actions = recorder.stop()
    types = [a.type for a in actions]
    assert types[:2] == ["click", "key_press"], types
    assert actions[0].params["pos"] == [300, 200]
    assert actions[1].params["key"] == "x"
    assert "scroll" in types

    backend = FakeBackend()
    result = MacroPlayer(backend).run(Macro("r", actions), PlaybackOptions(speed=10), threading.Event())
    assert result.status == "finished"
    assert ("click", "left", 1) in backend.events


def test_hotkey_manager_triggers():
    from pynput import keyboard

    from autoclique.core.hotkeys import HotkeyManager

    triggered = []
    manager = HotkeyManager(lambda b, kind: triggered.append((b, kind)))
    manager.set_bindings({"test": "ctrl+f7"})
    manager.start()
    try:
        time.sleep(0.2)
        k = keyboard.Controller()
        with k.pressed(keyboard.Key.ctrl):
            k.press(keyboard.Key.f7)
            k.release(keyboard.Key.f7)
        assert wait_for(lambda: ("test", "release") in triggered)
        assert triggered[0] == ("test", "press")
    finally:
        manager.stop()


def test_screen_capture():
    from autoclique.core.screen import ScreenCapture

    capture = ScreenCapture()
    left, top, width, height = capture.virtual_screen()
    assert width > 0 and height > 0
    shot = capture.grab((left, top, 50, 40))
    assert shot.pixels.shape == (40, 50, 3)
    assert len(capture.pixel(left + 1, top + 1)) == 3


def test_full_gui_flow_with_real_hotkeys(tmp_path):
    """Enregistrement (F8), lecture (F9), auto-clic (F6) et arrêt (Échap) de bout en bout."""
    import tkinter as tk

    from pynput import keyboard, mouse

    from autoclique.gui.main_window import App

    root = tk.Tk()
    app = App(root, data_folder=tmp_path)
    app.settings.minimize_on_run = False
    app.settings.failsafe = False
    k, m = keyboard.Controller(), mouse.Controller()

    def pump(until, timeout=5.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            root.update()
            if until():
                return True
            time.sleep(0.01)
        return until()

    def tap(key):
        k.press(key)
        time.sleep(0.03)
        k.release(key)

    try:
        assert app.hotkeys is not None
        pump(lambda: False, 0.3)
        # --- enregistrement
        tap(keyboard.Key.f8)
        assert pump(lambda: app.recorder is not None)
        # Un clic sur la fenêtre d'Autoclique est ignoré, un clic ailleurs est enregistré.
        m.position = (100, 100)
        time.sleep(0.05)
        m.click(mouse.Button.left)
        width, height = root.winfo_screenwidth(), root.winfo_screenheight()
        outside = (width - 30, height - 30)
        m.position = outside
        time.sleep(0.05)
        m.click(mouse.Button.left)
        time.sleep(0.05)
        tap("z")
        time.sleep(0.05)
        tap(keyboard.Key.f8)
        assert pump(lambda: app.recorder is None)
        macro = app.macros_tab.macro
        assert macro.name.startswith("Enregistrement du")
        types = [a.type for a in macro.actions]
        assert "click" in types and "key_press" in types, types
        assert [a.params["pos"] for a in macro.actions if a.type == "click"] == [list(outside)]
        assert all(a.params.get("key") != "f8" for a in macro.actions)

        # --- lecture : le curseur doit revenir au point cliqué
        m.position = (10, 10)
        clicks = []
        # (un rappel qui renvoie False arrêterait l'écouteur)
        listener = mouse.Listener(on_click=lambda x, y, b, p: clicks.append((x, y)) if p else None)
        listener.start()
        listener.wait()
        tap(keyboard.Key.f9)
        assert pump(lambda: app.task_kind == "macro", 2)
        assert pump(lambda: app.task is None, 10)
        assert outside in clicks
        assert "terminée" in app.status_text.cget("text")

        # --- auto-clic au raccourci (hors de notre fenêtre), puis arrêt d'urgence
        app.clicker_tab.millis.set("20")
        app.clicker_tab.repeat.set("infinite")
        m.position = (width - 20, height - 20)
        clicks.clear()
        tap(keyboard.Key.f6)
        assert pump(lambda: app.task_kind == "clicker", 2)
        pump(lambda: False, 0.4)
        tap(keyboard.Key.esc)
        assert pump(lambda: app.task is None, 3)
        listener.stop()
        assert len(clicks) > 5
    finally:
        app.close()
