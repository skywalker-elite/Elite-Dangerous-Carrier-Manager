"""Startup precedence and cache recovery without opening application windows."""
from types import SimpleNamespace
from unittest.mock import Mock
import pickle
import sys

import pytest

import main as module


class CachedReader:
    def __init__(self, fail=False):
        self.reads = 0
        self.fail = fail

    def read_journals(self):
        self.reads += 1
        if self.fail:
            raise ValueError('incompatible cache')


@pytest.mark.parametrize('kind', ['valid', 'corrupt', 'incompatible', 'absent'])
def test_cache_is_smoke_tested_and_bad_cache_is_removed(tmp_path, monkeypatch, kind):
    target = tmp_path / 'journal.pickle'
    monkeypatch.setattr(module, 'getCachePath', lambda *args: str(target))
    if kind == 'valid':
        target.write_bytes(pickle.dumps(CachedReader()))
    elif kind == 'incompatible':
        target.write_bytes(pickle.dumps(CachedReader(fail=True)))
    elif kind == 'corrupt':
        target.write_bytes(b'not a pickle')
    result = module.load_journal_reader_from_cache('version', [str(tmp_path)])
    if kind == 'valid':
        assert result.reads == 1
        assert target.exists()
    else:
        assert result is None
        assert not target.exists()


def test_cache_cleanup_permission_error_still_returns_fallback(tmp_path, monkeypatch):
    target = tmp_path / 'journal.pickle'
    target.write_bytes(b'corrupt')
    monkeypatch.setattr(module, 'getCachePath', lambda *args: str(target))
    monkeypatch.setattr(module.os, 'remove', Mock(side_effect=PermissionError('locked')))
    assert module.load_journal_reader_from_cache('version', [str(tmp_path)]) is None
    assert target.read_bytes() == b'corrupt'


def test_no_cache_path_returns_fallback(monkeypatch):
    monkeypatch.setattr(module, 'getCachePath', lambda *args: None)
    assert module.load_journal_reader_from_cache('version', ['journals']) is None


@pytest.fixture
def startup(monkeypatch, tmp_path):
    paths = {}
    for name in ('cli-a', 'cli-b', 'env-a', 'env-b', 'default'):
        directory = tmp_path / name
        directory.mkdir()
        paths[name] = str(directory)
    monkeypatch.setattr(sys, 'argv', ['edcm'])
    monkeypatch.delenv('EDCM_JOURNAL_PATHS', raising=False)
    monkeypatch.setattr(module, 'getJournalPath', lambda: paths['default'])
    cache_reader = object()
    monkeypatch.setattr(module, 'load_journal_reader_from_cache', Mock(return_value=cache_reader))
    model = Mock()
    monkeypatch.setattr(module, 'CarrierModel', model)
    root = Mock()
    monkeypatch.setattr(module.tk, 'Tk', Mock(return_value=root))
    monkeypatch.setattr(module, 'apply_theme_to_titlebar', Mock())
    monkeypatch.setattr(module.sv_ttk, 'use_dark_theme', Mock())
    photo = Mock(width=64, height=64)
    monkeypatch.setattr(module.Image, 'open', Mock(return_value=photo))
    monkeypatch.setattr(module.ImageTk, 'PhotoImage', Mock())
    controller = Mock()
    monkeypatch.setattr(module, 'CarrierController', controller)
    monkeypatch.setitem(sys.modules, 'pyi_splash', SimpleNamespace(update_text=Mock(), close=Mock()))
    return SimpleNamespace(paths=paths, model=model, reader=cache_reader, root=root, controller=controller)


@pytest.mark.parametrize('source', ['cli', 'environment', 'default', 'blank_environment'])
def test_startup_selects_paths_in_cli_environment_default_order(startup, monkeypatch, source):
    paths = startup.paths
    if source == 'cli':
        monkeypatch.setattr(sys, 'argv', ['edcm', '--paths', paths['cli-a'], paths['cli-b']])
        monkeypatch.setenv('EDCM_JOURNAL_PATHS', paths['env-a'])
        expected = [paths['cli-a'], paths['cli-b']]
    elif source == 'environment':
        monkeypatch.setenv('EDCM_JOURNAL_PATHS', f"  {paths['env-a']} ; ; {paths['env-b']} ; ")
        expected = [paths['env-a'], paths['env-b']]
    else:
        if source == 'blank_environment':
            monkeypatch.setenv('EDCM_JOURNAL_PATHS', '   ')
        expected = [paths['default']]
    module.main()
    startup.model.assert_called_once_with(expected, journal_reader=startup.reader)
    startup.controller.assert_called_once_with(startup.root, model=startup.model.return_value)
    startup.root.mainloop.assert_called_once()


def test_no_default_path_explains_how_to_select_journals(startup, monkeypatch):
    monkeypatch.setattr(module, 'getJournalPath', lambda: None)
    with pytest.raises(AssertionError, match='--paths'):
        module.main()
    startup.model.assert_not_called()


def test_startup_continues_with_healthy_path_when_another_is_unavailable(startup, tmp_path, monkeypatch):
    healthy = startup.paths['cli-a']
    absent = str(tmp_path / 'unavailable-journals')
    monkeypatch.setattr(sys, 'argv', ['edcm', '--paths', absent, healthy])
    module.main()
    assert startup.model.called
    assert healthy in startup.model.call_args.args[0]
    startup.root.mainloop.assert_called_once()
