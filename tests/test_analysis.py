import pytest

from autoclique.core.actions import Action
from autoclique.core.macro import analyze, find_block_end


def A(type_id, **params):
    return Action.new(type_id, **params)


def test_nested_structure_matching():
    actions = [
        A("loop_start", count=2),   # 0
        A("click"),                 # 1
        A("if_pixel"),              # 2
        A("break"),                 # 3
        A("else"),                  # 4
        A("loop_start", count=3),   # 5
        A("wait"),                  # 6
        A("loop_end"),              # 7
        A("end_if"),                # 8
        A("loop_end"),              # 9
    ]
    info = analyze(actions)
    assert info.ok, info.errors
    assert info.match[0] == 9 and info.match[9] == 0
    assert info.match[5] == 7 and info.match[7] == 5
    assert info.match[2] == 4  # condition -> Sinon
    assert info.match[4] == 8  # Sinon -> Fin si
    assert info.match[3] == 9  # Sortir -> fin de la boucle englobante
    assert info.depth == [0, 1, 1, 2, 1, 2, 3, 2, 1, 0]
    assert find_block_end(actions, 0) == 9
    assert find_block_end(actions, 2) == 8
    assert find_block_end(actions, 1) is None


def test_if_without_else_matches_end():
    info = analyze([A("if_image"), A("click"), A("end_if")])
    assert info.ok
    assert info.match[0] == 2


def test_errors_are_reported():
    info = analyze([A("loop_start"), A("click")])
    assert [i for i, _ in info.errors] == [0]
    assert "n'est pas fermé" in info.errors[0][1]

    info = analyze([A("loop_end")])
    assert info.errors[0][0] == 0

    info = analyze([A("else")])
    assert "sans condition" in info.errors[0][1]

    info = analyze([A("break")])
    assert "en dehors" in info.errors[0][1]

    info = analyze([A("if_pixel"), A("else"), A("else"), A("end_if")])
    assert "en double" in info.errors[0][1]

    info = analyze([A("loop_start"), A("if_pixel"), A("loop_end"), A("end_if")])
    assert not info.ok
    assert "Étape 3" in info.error_text()


def test_disabled_structure_is_ignored():
    start = A("loop_start")
    end = A("loop_end")
    start.enabled = False
    end.enabled = False
    assert analyze([start, A("click"), end]).ok
    start.enabled = True
    assert not analyze([start, A("click"), end]).ok


def test_error_text_limit():
    info = analyze([A("loop_end") for _ in range(8)])
    text = info.error_text(limit=3)
    assert text.count("Étape") == 3
    assert "5 autre(s)" in text


def test_estimate_duration():
    from autoclique.core.macro import estimate_duration

    actions = [
        A("click", hold=100),                     # 0,1 s
        A("loop_start", count=3),
        A("wait", duration=500),                  # 3 × 0,5 s
        A("key_press", key="a", hold=50),          # 3 × 0,05 s
        A("loop_end"),
    ]
    actions[0].delay = 200                        # 0,2 s
    estimate = estimate_duration(actions)
    assert estimate.seconds == pytest.approx(0.3 + 1.65)
    assert not estimate.variable and not estimate.infinite

    estimate = estimate_duration([A("loop_start", count=0), A("click"), A("loop_end")])
    assert estimate.infinite

    estimate = estimate_duration([A("if_pixel"), A("wait", duration=1000), A("else"),
                                  A("wait", duration=3000), A("end_if"), A("wait_image")])
    assert estimate.seconds == pytest.approx(3.0)
    assert estimate.variable

    assert estimate_duration([A("loop_start")]).variable
