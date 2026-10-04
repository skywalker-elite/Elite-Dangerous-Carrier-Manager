"""User settings, config overrides, and structured validation in isolated files."""
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomlkit

import settings as settings_module
from settings import Settings, SettingsValidationError


@pytest.fixture
def settings_defaults():
    """Read fixture inputs independently from the application's loading code."""
    defaults = Path(settings_module.getSettingsDefaultPath()).read_text(encoding="utf-8")
    config_defaults = Path(settings_module.getConfigSettingsDefaultPath()).read_text(encoding="utf-8")
    return SimpleNamespace(
        toml_text=defaults, config_text=config_defaults,
        user=tomllib.loads(defaults), config=json.loads(config_defaults),
    )


@pytest.fixture
def settings_files(tmp_path, monkeypatch, settings_defaults):
    defaults = settings_defaults.toml_text
    config_defaults = settings_defaults.config_text
    default_file = tmp_path / "defaults.toml"
    default_file.write_text(defaults, encoding="utf-8")
    config_default = tmp_path / "config-default.json"
    config_default.write_text(config_defaults, encoding="utf-8")
    user_file = tmp_path / "settings.toml"
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(settings_module, "getSettingsDefaultPath", lambda: str(default_file))
    monkeypatch.setattr(settings_module, "getConfigSettingsDefaultPath", lambda: str(config_default))
    monkeypatch.setattr(settings_module, "getConfigSettingsPath", lambda: str(config_file))

    def make(*, update=None, config=None):
        document = tomlkit.parse(defaults)
        if update:
            update(document)
        # Rebuild the document so a section replaced by a scalar is serialized
        # at the root, rather than under the preceding table's header.
        rebuilt = tomlkit.document()
        for key, value in document.items():
            rebuilt.add(key, value)
        user_file.write_text(tomlkit.dumps(rebuilt), encoding="utf-8")
        if config is not None:
            config_file.write_text(json.dumps(config), encoding="utf-8")
        return Settings(str(user_file))

    return make, user_file, config_file


def test_defaults_and_new_config_are_loaded(settings_files, settings_defaults):
    make, _, config_file = settings_files
    settings = make()
    assert settings.get("plot_reminders", "remind_seconds") == settings_defaults.user["plot_reminders"]["remind_seconds"]
    assert settings.get("timer_reporting", "enabled") == settings_defaults.config["timer_reporting"]["enabled"]
    assert settings.get("notifications", "jump_completed") == settings_defaults.user["notifications"]["jump_completed"]
    assert Path(settings.get("notifications", "jump_completed_sound_file")).is_file()
    assert json.loads(config_file.read_text())["timer_reporting"]["enabled"] == settings_defaults.config["timer_reporting"]["enabled"]
    assert not settings.validation_errors


def test_config_overrides_are_deep_merged_and_persisted(settings_files, settings_defaults):
    make, user_file, config_file = settings_files
    settings = make(config={"plot_reminders": {"warn_seconds": 20}, "UI": {"minimize_to_tray": True}})
    assert settings.get("plot_reminders", "warn_seconds") == 20
    assert settings.get("plot_reminders", "remind_seconds") == settings_defaults.user["plot_reminders"]["remind_seconds"]
    settings.set_config("UI", "minimize_to_tray", value=False)
    assert json.loads(config_file.read_text())["UI"]["minimize_to_tray"] is False
    assert Settings(str(user_file)).get("UI", "minimize_to_tray") is False


def test_missing_config_key_is_restored_from_defaults(settings_files, settings_defaults):
    make, _, config_file = settings_files
    settings = make(config={})
    assert settings.get("timer_reporting", "enabled") == settings_defaults.config["timer_reporting"]["enabled"]
    assert json.loads(config_file.read_text())["timer_reporting"]["enabled"] == settings_defaults.config["timer_reporting"]["enabled"]
    assert settings.get("does_not_exist") is None


def test_missing_user_keys_filled_and_unknown_keys_warn(settings_files, settings_defaults):
    make, user_file, _ = settings_files

    def update(document):
        del document["plot_reminders"]["warn_seconds"]
        document["custom_option"] = "kept"

    settings = make(update=update)
    assert settings.get("plot_reminders", "warn_seconds") == settings_defaults.user["plot_reminders"]["warn_seconds"]
    assert any("plot_reminders.warn_seconds" in value for value in settings.auto_update_info)
    assert any("custom_option" in value for value in settings.validation_warnings)
    settings.merge_user_into_defaults()
    saved = tomlkit.parse(user_file.read_text(encoding="utf-8"))
    assert saved["custom_option"] == "kept"
    assert saved["plot_reminders"]["warn_seconds"] == settings_defaults.user["plot_reminders"]["warn_seconds"]


def test_user_changes_survive_save_and_reload(settings_files):
    make, user_file, _ = settings_files
    settings = make()
    settings.set("font_size", {"UI": "large", "table": "small"})
    settings.save()
    reloaded = Settings(str(user_file))
    assert reloaded.get("font_size", "UI") == "large"
    assert reloaded.get("font_size", "table") == "small"


def test_malformed_config_uses_defaults_and_records_warning(settings_files, settings_defaults):
    make, user_file, config_file = settings_files
    make()
    config_file.write_text('{"broken":', encoding="utf-8")
    settings = Settings(str(user_file))
    assert settings.get("timer_reporting", "enabled") == settings_defaults.config["timer_reporting"]["enabled"]
    assert settings.validation_warnings


@pytest.mark.parametrize("section,key,value", [
    ("plot_reminders", "remind_seconds", 0),
    ("plot_reminders", "warn_seconds", -1),
    ("plot_reminders", "clear_seconds", -1),
    ("discord", "webhook", "https://invalid.example/webhook"),
    ("notifications", "jump_plotted_sound_file", "missing-sound-test.mp3"),
    ("name_customization", "squadron_abbv", [{"Example Squadron": "bad-code"}]),
])
def test_invalid_values_raise_structured_validation_error(settings_files, section, key, value):
    make, _, _ = settings_files
    with pytest.raises(SettingsValidationError) as error:
        make(update=lambda doc: doc[section].__setitem__(key, value))
    assert key in str(error.value)


def test_warning_must_precede_reminder(settings_files):
    make, _, _ = settings_files

    def update(document):
        reminders = document["plot_reminders"]
        reminders["warn_seconds"] = reminders["remind_seconds"]

    with pytest.raises(SettingsValidationError) as error:
        make(update=update)
    assert "warn_seconds" in str(error.value)


@pytest.mark.parametrize("section,key,value", [
    ("plot_reminders", "remind_seconds", "soon"),
    ("discord", "webhook", 123),
    ("name_customization", "squadron_abbv", [123]),
    ("plot_reminders", None, "not-a-section"),
])
def test_wrong_types_raise_structured_validation_error(settings_files, section, key, value):
    make, _, _ = settings_files

    def update(doc):
        if key is None:
            doc[section] = value
        else:
            doc[section][key] = value

    with pytest.raises(SettingsValidationError):
        make(update=update)
