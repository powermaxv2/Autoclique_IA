import json

import pytest

from autoclique.core.actions import Action
from autoclique.core.macro import Macro
from autoclique.core.settings import DEFAULT_HOTKEYS, Settings
from autoclique.core.storage import (
    MacroLibrary,
    data_dir,
    load_settings,
    safe_filename,
    save_settings,
    validate_name,
)


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTOCLIQUE_HOME", str(tmp_path / "x"))
    assert data_dir() == tmp_path / "x"


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.theme = "light"
    settings.hotkeys["clicker"] = "ctrl+f6"
    settings.clicker.interval_ms = 42
    settings.record.record_moves = False
    save_settings(settings, path)
    again = load_settings(path)
    assert again.to_dict() == settings.to_dict()


def test_settings_defaults_and_corruption(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path).hotkeys == DEFAULT_HOTKEYS
    path.write_text("{ceci n'est pas du json", encoding="utf-8")
    assert load_settings(path).theme == "dark"
    assert (tmp_path / "settings.json.bak").exists()
    path.write_text(json.dumps({"theme": "violet", "default_delay": 10**9,
                                "hotkeys": {"clicker": 5, "play": "f2"}}), encoding="utf-8")
    settings = load_settings(path)
    assert settings.theme == "dark"
    assert settings.default_delay == 60000
    assert settings.hotkeys["clicker"] == "f6"
    assert settings.hotkeys["play"] == "f2"


def test_library_save_load_rename_delete(tmp_path):
    lib = MacroLibrary(tmp_path / "macros")
    macro = Macro("Ma macro", [Action.new("click", pos=[1, 2])], hotkey="ctrl+f1")
    path = lib.save(macro)
    assert path.name == "Ma macro.json"
    assert lib.names() == ["Ma macro"]
    loaded = lib.load("ma MACRO")  # insensible à la casse
    assert loaded.name == "Ma macro"
    assert loaded.actions[0].params["pos"] == [1, 2]

    loaded.name = "Renommée"
    lib.save(loaded, previous_name="Ma macro")
    assert lib.names() == ["Renommée"]
    assert not path.exists()
    assert lib.hotkeys() == {"Renommée": "ctrl+f1"}

    with pytest.raises(ValueError):
        lib.save(Macro("renommée"))  # doublon (casse différente)

    lib.delete("Renommée")
    assert lib.names() == []
    assert lib.get("Renommée") is None


def test_library_resave_same_name_keeps_file(tmp_path):
    lib = MacroLibrary(tmp_path)
    macro = Macro("A")
    first = lib.save(macro)
    macro.actions.append(Action.new("wait"))
    second = lib.save(macro, previous_name="A")
    assert first == second
    assert len(lib.load("A").actions) == 1


def test_library_weird_names(tmp_path):
    lib = MacroLibrary(tmp_path)
    lib.save(Macro("a/b"))
    lib.save(Macro("a_b"))
    lib.save(Macro("CON"))
    files = sorted(p.name for p in tmp_path.glob("*.json"))
    assert files == ["_CON.json", "a_b (2).json", "a_b.json"]
    lib.refresh()
    assert lib.names() == ["a/b", "a_b", "CON"]


def test_library_refresh_reports_errors(tmp_path):
    (tmp_path / "cassée.json").write_text("{", encoding="utf-8")
    (tmp_path / "ok.json").write_text(Macro("Ok").to_json(), encoding="utf-8")
    lib = MacroLibrary(tmp_path)
    assert lib.names() == ["Ok"]
    assert len(lib.errors) == 1


def test_library_import_export(tmp_path):
    lib = MacroLibrary(tmp_path / "lib")
    lib.save(Macro("Partagée", [Action.new("wait")]))
    exported = tmp_path / "export.json"
    lib.export("Partagée", exported)
    imported = lib.import_file(exported)
    assert imported.name == "Partagée (2)"
    assert lib.names() == ["Partagée", "Partagée (2)"]
    assert lib.unique_name("Partagée") == "Partagée (3)"


def test_library_cache_refreshes_on_change(tmp_path):
    lib = MacroLibrary(tmp_path)
    macro = Macro("C", [Action.new("wait")])
    lib.save(macro)
    first = lib.load("C")
    first.actions.clear()  # la copie renvoyée ne modifie pas le cache
    assert len(lib.load("C").actions) == 1


def test_validate_name_and_filename():
    assert validate_name("  deux   espaces ") == "deux espaces"
    with pytest.raises(ValueError):
        validate_name("   ")
    with pytest.raises(ValueError):
        validate_name("x" * 101)
    assert safe_filename('a<b>c:"d"') == "a_b_c__d_"
    assert safe_filename("...") == "macro"
