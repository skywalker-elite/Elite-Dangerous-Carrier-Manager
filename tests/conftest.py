"""Shared isolation applies to diagnostics as well as regression tests."""

import locale
import os
from pathlib import Path
import re
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

# These must precede imports of auth, main, controller, or pystray.
os.environ["PYSTRAY_BACKEND"] = "dummy"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
_dotenv_patch = patch("dotenv.load_dotenv", return_value=False)
_dotenv_patch.start()

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config):
    """Separate runs even when different Windows accounts share USERNAME."""
    if config.getoption("basetemp") is not None or os.environ.get("PYTEST_DEBUG_TEMPROOT"):
        return
    temp_root = config.rootpath / ".cache" / "pytest"
    temp_root.mkdir(parents=True, exist_ok=True)
    # pytest uses USERNAME for its directory name but Windows grants 0o700
    # access to the actual process account. Sandbox and interactive processes
    # can therefore collide on a directory that only one of them can access.
    run_root = TemporaryDirectory(prefix="run-", dir=temp_root)
    config.add_cleanup(run_root.cleanup)
    environment = pytest.MonkeyPatch()
    config.add_cleanup(environment.undo)
    environment.setenv("PYTEST_DEBUG_TEMPROOT", run_root.name)


def pytest_unconfigure(config):
    _dotenv_patch.stop()


def pytest_collection_modifyitems(items):
    """Reject undocumented marker syntax instead of silently quarantining tests."""
    report = Path(__file__).resolve().parents[1] / "docs" / "TEST_DEFECTS.md"
    documented_ids = set(re.findall(r"\b[A-Z]+-\d{3}\b", report.read_text(encoding="utf-8")))
    for item in items:
        marker = item.get_closest_marker("known_defect")
        if marker is not None:
            if len(marker.args) != 1 or not isinstance(marker.args[0], str):
                raise pytest.UsageError(f"{item.nodeid}: known_defect requires a defect ID")
            if marker.args[0] not in documented_ids:
                raise pytest.UsageError(f"{item.nodeid}: undocumented defect ID {marker.args[0]}")
            item.user_properties.append(("defect_id", marker.args[0]))


@pytest.fixture(autouse=True)
def isolated_app(monkeypatch, tmp_path):
    """Unexpected external work fails; individual tests explicitly replace boundaries."""
    import httpx
    import keyring
    import pyperclip
    import requests
    import utility
    import webbrowser

    unexpected_operations = []

    def unexpected(*args, **kwargs):
        unexpected_operations.append(True)
        raise AssertionError("External operation was not faked by the test")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, unexpected)
    monkeypatch.setattr(socket, "create_connection", unexpected)
    monkeypatch.setattr(socket, "getaddrinfo", unexpected)
    monkeypatch.setattr(requests.sessions.Session, "request", unexpected)
    monkeypatch.setattr(httpx.Client, "send", unexpected)
    monkeypatch.setattr(httpx.AsyncClient, "send", unexpected)
    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, unexpected)
    monkeypatch.setattr(webbrowser, "open", unexpected)
    monkeypatch.setattr(webbrowser, "open_new_tab", unexpected)
    monkeypatch.setattr(pyperclip, "copy", unexpected)
    monkeypatch.setattr(pyperclip, "paste", unexpected)
    if sys.platform == "win32":
        monkeypatch.setattr(os, "startfile", unexpected)
    # Controller imports these functions by value, before per-test fixtures run.
    if module := sys.modules.get("controller"):
        for name in ("playsound", "open_new_tab", "open_file"):
            monkeypatch.setattr(module, name, unexpected)
        monkeypatch.setattr(module.Observer, "start", unexpected)
        monkeypatch.setattr(module.Icon, "run", unexpected)

    app_dir = tmp_path / "app-data"
    app_dir.mkdir()
    monkeypatch.setattr(utility, "getSettingsDir", lambda: str(app_dir))
    monkeypatch.setattr(utility, "getAppDir", lambda: str(app_dir))
    if module := sys.modules.get("controller"):
        monkeypatch.setattr(module, "getSettingsDir", lambda: str(app_dir))
        monkeypatch.setattr(module, "getAppDir", lambda: str(app_dir))
    previous_locale = locale.setlocale(locale.LC_ALL)
    yield
    locale.setlocale(locale.LC_ALL, previous_locale)
    assert not unexpected_operations, "An unfaked external operation was attempted (possibly caught by application code)"


@pytest.fixture
def tk_root():
    """Use actual widgets and surface errors otherwise swallowed by the Tk loop."""
    import tkinter as tk
    import sv_ttk

    root = tk.Tk()
    errors = []
    try:
        root.withdraw()
        root.report_callback_exception = lambda kind, value, tb: errors.append(value)
        sv_ttk.use_dark_theme(root=root)
        yield root
        root.update_idletasks()
    finally:
        # A test may already have closed the root. Do not swallow cleanup errors
        # from a still-live window: they can leak an implicit root into later tests.
        if root.tk.call('info', 'commands', '.'):
            for callback in root.tk.splitlist(root.tk.call("after", "info")):
                # These callbacks may belong to child widgets. Root.after_cancel
                # deletes their Tcl commands without updating child bookkeeping,
                # making destroy() double-delete them and leak the default root.
                root.tk.call('after', 'cancel', callback)
            root.destroy()
        assert tk._default_root is not root, 'Tk root leaked into the next test'
    assert not errors, f"Unhandled Tk callback errors: {errors!r}"
