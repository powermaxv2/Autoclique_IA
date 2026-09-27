import pytest

from autoclique.core.actions import Action
from autoclique.core.macro import Macro
from autoclique.core.player import PlaybackOptions


def A(type_id, delay=0, **params):
    return Action.new(type_id, delay=delay, **params)


def run(player, actions, stop, **options):
    macro = Macro("Test", actions)
    return player.run(macro, PlaybackOptions(**options), stop)


def test_basic_sequence(make_player, backend, stop):
    result = run(make_player(), [
        A("click", pos=[10, 20]),
        A("key_press", key="a", hold=0),
        A("type_text", text="hé"),
        A("scroll", dy=-2),
        A("mouse_down", button="right"),
        A("mouse_up", button="right", pos=[3, 4]),
    ], stop)
    assert result.status == "finished"
    assert backend.events == [
        ("move", 10, 20), ("click", "left", 1),
        ("key_down", "a"), ("key_up", "a"),
        ("type", "h"), ("type", "é"),
        ("scroll", 0, -2),
        ("down", "right"), ("move", 3, 4), ("up", "right"),
    ]
    assert result.steps == 6


def test_delays_and_speed(make_player, backend, clock, stop):
    t0 = clock.now()
    run(make_player(), [A("click", delay=100), A("click", delay=300), A("wait", duration=600),
                        A("click")], stop, speed=2.0)
    times = [round(t - t0, 3) for t in backend.times]
    assert times == [0.05, 0.2, 0.5]


def test_hold_durations(make_player, backend, clock, stop):
    t0 = clock.now()
    run(make_player(), [A("click", hold=200), A("key_press", key="b", hold=50)], stop)
    assert backend.kinds() == ["down", "up", "key_down", "key_up"]
    assert [round(t - t0, 3) for t in backend.times] == [0, 0.2, 0.2, 0.25]


def test_loops(make_player, backend, stop):
    result = run(make_player(), [
        A("loop_start", count=2),
        A("loop_start", count=3),
        A("click"),
        A("loop_end"),
        A("key_press", key="x", hold=0),
        A("loop_end"),
    ], stop)
    assert result.status == "finished"
    assert backend.kinds().count("click") == 6
    assert backend.kinds().count("key_down") == 2


def test_infinite_loop_with_break(make_player, backend, screen, stop):
    # La couleur devient rouge au 4e contrôle : on sort alors de la boucle.
    screen.pixel_sequence = [(0, 0, 0)] * 3 + [(255, 0, 0)]
    result = run(make_player(), [
        A("loop_start", count=0),
        A("if_pixel", pos=[1, 1], color="#FF0000", tolerance=0),
        A("break"),
        A("end_if"),
        A("click"),
        A("loop_end"),
        A("key_press", key="z", hold=0),
    ], stop)
    assert result.status == "finished"
    assert backend.kinds().count("click") == 3
    assert backend.events[-1] == ("key_up", "z")


def test_if_else(make_player, backend, screen, stop):
    screen.pixels[(5, 5)] = (250, 10, 10)
    actions = [
        A("if_pixel", pos=[5, 5], color="#FF0000", tolerance=10),
        A("key_press", key="y", hold=0),
        A("else"),
        A("key_press", key="n", hold=0),
        A("end_if"),
    ]
    run(make_player(), actions, stop)
    assert backend.events == [("key_down", "y"), ("key_up", "y")]
    backend.events.clear()
    actions[0].params["negate"] = True
    run(make_player(), actions, stop)
    assert backend.events == [("key_down", "n"), ("key_up", "n")]


def test_if_image(make_player, backend, screen, stop):
    screen.matches = [None]
    run(make_player(), [A("if_image", image="x"), A("click"), A("end_if")], stop)
    assert backend.events == []
    screen.matches = [(40, 50)]
    run(make_player(), [A("if_image", image="x"), A("click"), A("end_if")], stop)
    assert backend.kinds() == ["click"]


def test_stop_action(make_player, backend, stop):
    result = run(make_player(), [A("click"), A("stop"), A("click")], stop, repeat=5)
    assert result.status == "finished"
    assert "Arrêter la macro" in result.message
    assert backend.kinds() == ["click"]


def test_repeat_and_loop_delay(make_player, backend, clock, stop):
    t0 = clock.now()
    result = run(make_player(), [A("click")], stop, repeat=3, loop_delay=1000)
    assert result.iterations == 3
    assert [round(t - t0, 3) for t in backend.times] == [0, 1, 2]


def test_run_macro(make_player, backend, stop):
    library = {"Sous": Macro("Sous", [A("key_press", key="s", hold=0)])}
    player = make_player(resolve=library.get)
    result = run(player, [A("run_macro", macro="Sous", repeat=2), A("click")], stop)
    assert result.status == "finished"
    assert backend.kinds() == ["key_down", "key_up", "key_down", "key_up", "click"]


def test_run_macro_errors(make_player, stop):
    library = {"Boucle": Macro("Boucle", [A("run_macro", macro="Boucle")])}
    result = run(make_player(resolve=library.get), [A("run_macro", macro="Boucle")], stop)
    assert result.status == "error"
    assert "imbriqués" in result.message
    result = run(make_player(resolve=library.get), [A("click"), A("run_macro", macro="Absente")], stop)
    assert result.status == "error"
    assert "introuvable" in result.message
    assert result.error_index == 1


def test_wait_image_timeout(make_player, screen, clock, stop):
    screen.matches = [None]
    t0 = clock.now()
    result = run(make_player(), [A("wait_image", image="x", timeout=2, on_timeout="continue"),
                                 A("click")], stop)
    assert result.status == "finished"
    assert clock.now() - t0 == pytest.approx(2.0, abs=0.2)
    result = run(make_player(), [A("wait_image", image="x", timeout=1, on_timeout="stop"),
                                 A("click")], stop)
    assert result.status == "aborted"
    assert "introuvable" in result.message


def test_wait_image_found_later(make_player, screen, stop):
    screen.matches = [None, None, (7, 8)]
    result = run(make_player(), [A("wait_image", image="x", timeout=0)], stop)
    assert result.status == "finished"
    assert screen.locate_calls == 3


def test_click_image(make_player, backend, screen, stop):
    screen.matches = [(100, 200)]
    run(make_player(), [A("click_image", image="x", offset_x=5, offset_y=-5, count=2,
                          button="right")], stop)
    assert backend.events == [("move", 105, 195), ("click", "right", 2)]


def test_missing_image_is_error(make_player, stop):
    result = run(make_player(), [A("click_image")], stop)
    assert result.status == "error"
    assert "Aucune image" in result.message


def test_wait_pixel(make_player, screen, stop):
    screen.pixel_sequence = [(0, 0, 0), (0, 0, 0), (10, 20, 30)]
    result = run(make_player(), [A("wait_pixel", pos=[1, 2], color="#0A141E", tolerance=0,
                                   timeout=10)], stop)
    assert result.status == "finished"
    assert screen.pixel_calls == 3


def test_hotkey_action(make_player, backend, stop):
    run(make_player(), [A("hotkey", keys="ctrl+shift+s")], stop)
    assert backend.events == [
        ("key_down", "ctrl"), ("key_down", "shift"), ("key_down", "s"),
        ("key_up", "s"), ("key_up", "shift"), ("key_up", "ctrl"),
    ]
    result = run(make_player(), [A("hotkey", keys="ctrl+mouse_x1")], stop)
    assert result.status == "error"


def test_invalid_key_is_error(make_player, stop):
    result = run(make_player(), [A("key_press", key="n'existe pas")], stop)
    assert result.status == "error"
    assert "Touche inconnue" in result.message


def test_move_with_duration(make_player, backend, clock, stop):
    backend.pos = (0, 0)
    t0 = clock.now()
    run(make_player(), [A("move", pos=[100, 50], duration=200)], stop)
    moves = [e for e in backend.events if e[0] == "move"]
    assert len(moves) == 20
    assert moves[-1] == ("move", 100, 50)
    assert clock.now() - t0 == pytest.approx(0.2)
    xs = [m[1] for m in moves]
    assert xs == sorted(xs)


def test_relative_move(make_player, backend, stop):
    backend.pos = (10, 10)
    run(make_player(), [A("move", pos=[5, -3], relative=True)], stop)
    assert backend.pos == (15, 7)


def test_stop_event_and_release(make_player, backend, clock, stop):
    player = make_player()
    # L'arrêt est demandé pendant l'attente qui suit l'appui sur Maj.
    original = clock.wait_until

    def wait_until(deadline, event):
        stop.set()
        return original(deadline, event)

    clock.wait_until = wait_until
    result = run(player, [A("key_down", key="shift"), A("wait", duration=5000), A("click")], stop)
    assert result.status == "stopped"
    assert backend.events == [("key_down", "shift"), ("key_up", "shift")]


def test_start_index_inside_loop(make_player, backend, stop):
    actions = [
        A("loop_start", count=3),
        A("key_press", key="a", hold=0),
        A("click"),
        A("loop_end"),
        A("key_press", key="b", hold=0),
    ]
    run(make_player(), actions, stop, start_index=2)
    assert backend.kinds() == ["click", "key_down", "key_up"]


def test_failsafe(make_player, backend, stop):
    backend.pos = (0, 0)
    result = run(make_player(), [A("click")], stop, failsafe=True)
    assert result.status == "failsafe"
    assert backend.events == []


def test_humanize_bounds(make_player, backend, clock, stop):
    t0 = clock.now()
    run(make_player(), [A("click", delay=1000)] * 20, stop, humanize=10)
    gaps = [b - a for a, b in zip([t0] + backend.times[:-1], backend.times)]
    assert all(0.9 - 1e-9 <= g <= 1.1 + 1e-9 for g in gaps)
    assert len({round(g, 6) for g in gaps}) > 1


def test_structure_errors_prevent_playback(make_player, backend, stop):
    result = run(make_player(), [A("click"), A("loop_start")], stop)
    assert result.status == "error"
    assert "Étape 2" in result.message
    assert backend.events == []


def test_disabled_actions_are_skipped(make_player, backend, stop):
    skipped = A("click", button="right")
    skipped.enabled = False
    run(make_player(), [skipped, A("click")], stop)
    assert backend.events == [("click", "left", 1)]


def test_open_and_focus(make_player, system, stop):
    system.windows = ["Bloc-notes - sans titre"]
    result = run(make_player(), [
        A("open", target="notepad.exe", args="a.txt"),
        A("focus_window", title="bloc-notes", timeout=1),
        A("focus_window", title="absente", timeout=1, on_timeout="stop"),
    ], stop)
    assert system.opened == [("notepad.exe", "a.txt")]
    assert system.focused == ["bloc-notes"]
    assert result.status == "aborted"


def test_empty_macro(make_player, stop):
    result = run(make_player(), [], stop, repeat=0)
    assert result.status == "finished"
    assert "aucune action" in result.message


def test_progress_tracking(make_player, stop):
    player = make_player()
    run(player, [A("click"), A("click"), A("click")], stop, repeat=2)
    assert player.current_index == 2
    assert player.iteration == 2
