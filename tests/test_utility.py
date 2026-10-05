"""Pure transforms, local paths, cache identity and HTTP-derived values."""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import requests

import utility


@pytest.mark.parametrize("seconds,expected", [(0, (0, 0, 0)), (59, (0, 0, 59)), (60, (0, 1, 0)), (3661, (1, 1, 1)), (90061, (25, 1, 1)), (1.6, (0, 0, 2))])
def test_seconds_convert_to_hours_minutes_seconds(seconds, expected):
    assert utility.getHMS(seconds) == expected


@pytest.mark.parametrize("timer,expected", [
    ("00:00:00", True), ("23:59:59", True), ("24:00:00", False),
    ("00:60:00", False), ("00:00:60", False), ("1:02:03", False),
    ("01:02:03 trailing", False), ("-1:00:00", False), ("", False),
])
def test_timer_format_requires_valid_clock_time(timer, expected):
    assert utility.checkTimerFormat(timer) is expected


def test_discord_countdown_preserves_epoch_seconds():
    assert utility.getHammerCountdown(np.datetime64("1970-01-01T00:16:40")) == "<t:1000:R>"


def test_resource_path_supports_development_and_bundle(monkeypatch, tmp_path):
    monkeypatch.delattr(utility.sys, "_MEIPASS", raising=False)
    assert Path(utility.getResourcePath("VERSION")) == Path(utility.__file__).resolve().parent / "VERSION"
    monkeypatch.setattr(utility.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert Path(utility.getResourcePath("VERSION")) == tmp_path / "VERSION"


def test_current_version_reads_bundled_resource(monkeypatch, tmp_path):
    (tmp_path / "VERSION").write_text("1.2.3\n", encoding="utf-8")
    monkeypatch.setattr(utility.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert utility.getCurrentVersion() == "1.2.3"


@pytest.mark.parametrize("platform,expected_parts", [
    ("win32", ("Saved Games", "Frontier Developments", "Elite Dangerous")),
    ("linux", (".local", "share", "Steam", "steamapps", "compatdata", "359320")),
])
def test_journal_path_selects_platform_layout(monkeypatch, tmp_path, platform, expected_parts):
    monkeypatch.setattr(utility.sys, "platform", platform)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(utility.os.path, "expanduser", lambda value: str(tmp_path))
    path = Path(utility.getJournalPath())
    assert str(path).startswith(str(tmp_path))
    assert all(part in path.parts for part in expected_parts)


def test_unsupported_journal_platform_has_no_default(monkeypatch):
    monkeypatch.setattr(utility.sys, "platform", "unsupported")
    assert utility.getJournalPath() is None


def test_local_settings_notes_and_cache_paths_stay_in_app_dir(tmp_path):
    settings = Path(utility.getSettingsPath())
    assert settings.parent == Path(utility.getSettingsDir())
    assert Path(utility.getNotesPath()).parent == settings.parent
    assert Path(utility.getConfigSettingsPath()).parent == settings.parent
    first = utility.getCachePath("1", ["journal-one", "journal-two"])
    assert first == utility.getCachePath("1", ["journal-one", "journal-two"])
    assert first != utility.getCachePath("2", ["journal-one", "journal-two"])
    assert first != utility.getCachePath("1", ["journal-three"])
    assert Path(first).is_relative_to(Path(utility.getAppDir()))


def test_info_hash_is_stable_and_changes_with_input():
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    value = utility.getInfoHash(timestamp, 900, 123)
    assert len(value) == 40
    assert int(value, 16) >= 0
    assert value == utility.getInfoHash(timestamp, 900, 123)
    assert value != utility.getInfoHash(timestamp, 901, 123)
    assert value != utility.getInfoHash(timestamp, 900, 124)


@pytest.mark.parametrize("current,stable,prerelease,expected", [
    ("1.2.0", "1.2.1", None, True), ("1.2.0", "1.2.0", None, False),
    ("1.2.0", None, None, False), ("1.2.0rc1", "1.1.9", "1.2.0rc2", True),
    ("1.2.0", "1.1.9", "1.3.0rc1", False),
])
def test_update_selection_obeys_stable_and_prerelease_channels(monkeypatch, current, stable, prerelease, expected):
    monkeypatch.setattr(utility, "getCurrentVersion", lambda: current)
    monkeypatch.setattr(utility, "getLatestVersion", lambda: stable)
    monkeypatch.setattr(utility, "getLatestPrereleaseVersion", lambda: prerelease)
    assert utility.isUpdateAvailable() is expected


def test_prerelease_selection_uses_tags_and_filters_minor_and_invalid_tags(monkeypatch):
    response = Mock()
    response.json.return_value = [
        {"prerelease": True, "name": "Release refs/tags/v1.2.0rc1", "tag_name": "v1.2.0rc1"},
        {"prerelease": True, "name": "Preview with an arbitrary title", "tag_name": "v1.2.0rc2"},
        {"prerelease": True, "name": None, "tag_name": "v1.2.0rc3"},
        {"prerelease": True, "tag_name": "v1.2.0rc4"},
        {"prerelease": True, "tag_name": "v1.3.0rc9"},
        {"prerelease": True, "tag_name": "v2.2.0rc9"},
        {"prerelease": True, "name": "Release v1.2.0rc9", "tag_name": "not-a-version"},
        {"prerelease": True, "name": "Release v1.2.0rc9"},
        {"prerelease": True, "tag_name": None},
        {"prerelease": True, "tag_name": 123},
        {"prerelease": True, "tag_name": ""},
        {"prerelease": True, "tag_name": "v1.2.0"},
        {"prerelease": False, "tag_name": "v1.2.0rc9"},
    ]
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(return_value=response)))
    monkeypatch.setattr(utility, "getCurrentVersion", lambda: "1.2.0rc1")
    assert utility.getLatestPrereleaseVersion.__wrapped__() == "v1.2.0rc4"


@pytest.mark.parametrize("stable,prerelease,expected", [
    ("1.2.0", "1.2.0rc2", "1.2.0"), (None, "1.2.0rc2", "1.2.0rc2"),
    ("1.2.0", None, "1.2.0"), (None, None, None),
])
def test_prerelease_update_candidate_uses_highest_version(monkeypatch, stable, prerelease, expected):
    monkeypatch.setattr(utility, "getLatestVersion", lambda: stable)
    monkeypatch.setattr(utility, "getLatestPrereleaseVersion", lambda: prerelease)
    assert utility.getPrereleaseUpdateVersion() == expected


@pytest.mark.parametrize("title", [
    "Release v1.6.4", "Release refs/tags/v1.6.4", "An arbitrary title",
    "Release v9.9.9", "", None,
])
@pytest.mark.parametrize("tag", ["v1.6.4", "1.6.4"])
def test_latest_release_uses_tag_independently_of_title(monkeypatch, title, tag):
    response = Mock()
    response.json.return_value = {"name": title, "tag_name": tag}
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(return_value=response)))
    assert utility.getLatestVersion() == tag
    response.raise_for_status.assert_called_once_with()


def test_update_check_works_without_release_title(monkeypatch):
    response = Mock()
    response.json.return_value = {"tag_name": "v1.6.4"}
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(return_value=response)))
    monkeypatch.setattr(utility, "getCurrentVersion", lambda: "v1.6.3")
    assert utility.isUpdateAvailable() is True


@pytest.mark.parametrize("release", [
    {"name": "Release v1.6.4"}, {"tag_name": None}, {"tag_name": ""},
    {"tag_name": "not-a-version"}, {"tag_name": 123},
])
def test_invalid_latest_release_tag_returns_no_update(monkeypatch, release):
    response = Mock()
    response.json.return_value = release
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(return_value=response)))
    monkeypatch.setattr(utility, "getCurrentVersion", lambda: "v1.6.3")
    assert utility.getLatestVersion() is None
    assert utility.isUpdateAvailable() is False


@pytest.mark.parametrize("function", [utility.getLatestVersion, utility.getLatestPrereleaseVersion.__wrapped__])
@pytest.mark.parametrize("failure", [requests.Timeout("timeout"), requests.HTTPError("503")])
def test_update_request_failure_returns_no_version(monkeypatch, function, failure):
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(side_effect=failure)))
    assert function() is None


def test_jump_timer_response_converts_seconds_and_iso_timestamps(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = [{"avg": 1200, "cnt": 8, "earliest": "2026-01-01T01:00:00+00:00", "latest": "2026-01-01T02:00:00+00:00", "slope": -0.25}]
    post = Mock(return_value=response)
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(post=post))
    average, count, earliest, latest, slope = utility.getExpectedJumpTimer.__wrapped__()
    assert average == "00 h 20 m 00 s"
    assert count == 8 and slope == -0.25
    assert earliest == datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    assert latest == datetime(2026, 1, 1, 2, tzinfo=timezone.utc)
    assert latest > earliest
    assert post.call_args.args[0].endswith("/rpc/jump_timer_stats_cached")


@pytest.mark.parametrize("status,payload", [(503, None), (200, [None])])
def test_no_timer_data_has_consistent_empty_fields(monkeypatch, status, payload):
    response = Mock(status_code=status)
    response.json.return_value = payload
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(post=Mock(return_value=response)))
    assert utility.getExpectedJumpTimer.__wrapped__() == (None, None, None, None, None)


def test_cruise_status_extracts_state(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {"state": "preparation"}
    monkeypatch.setattr(utility, "HTTP_SESSION", SimpleNamespace(get=Mock(return_value=response)))
    assert utility.getCruiseStatus.__wrapped__() == "preparation"
