"""Finite real-Tk/model smoke coverage; no watchers, services or infinite loops."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from controller import CarrierController
from model import CarrierModel
from view import CarrierView
from tests.journal_helpers import (
    NOW, append_events, event, freeze_clock, sample_events, write_journal,
)

pytestmark = [pytest.mark.gui, pytest.mark.integration]


def build_app(tk_root, tmp_path, monkeypatch, events=None):
    freeze_clock(monkeypatch)
    journal = write_journal(tmp_path / 'journals', sample_events() if events is None else events)
    model = CarrierModel([str(journal.parent)])
    view = CarrierView(tk_root)
    ctl = CarrierController.__new__(CarrierController)
    ctl.root = tk_root
    ctl.model = model
    ctl.view = view
    ctl._ui_callbacks = Queue()
    # Fail loudly rather than displaying blocking popups in the test runner.
    def unexpected_popup(*args, **kwargs):
        pytest.fail(f'Unexpected GUI warning: {args!r}')
    monkeypatch.setattr(view, 'show_message_box_askretrycancel', unexpected_popup)
    monkeypatch.setattr(view, 'show_message_box_warning', unexpected_popup)
    monkeypatch.setattr('controller.getNotesPath', lambda: str(tmp_path / 'notes.csv'))
    return ctl, journal


def render_tables(ctl):
    ctl.update_tables_fast(NOW)
    ctl.update_tables_slow(NOW)
    ctl.view.update_table_active_journals(ctl.model.get_data_active_journals())
    ctl.load_notes()
    ctl.update_time(NOW)
    ctl.root.update_idletasks()
    ctl.root.update()


@pytest.mark.parametrize('missing_event', [None, 'Commander', 'LoadGame', 'CarrierBuy'])
def test_real_model_renders_all_tables_and_processes_incremental_update(tk_root, tmp_path, monkeypatch, missing_event):
    events = [record for record in sample_events() if record['event'] != missing_event]
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch, events)
    render_tables(ctl)
    for name in ('jumps', 'finance', 'trade', 'services', 'cmdr', 'misc', 'notes'):
        rows = getattr(ctl.view, 'sheet_' + name).get_sheet_data()
        assert rows[0][0] == 'Test Carrier', name
    assert len(ctl.view.sheet_active_journals.get_sheet_data()) == 1
    append_events(journal, event('CarrierLocation', 1, CarrierID=1, StarSystem='Achenar', BodyID=0))
    ctl._perform_journal_update()
    render_tables(ctl)
    assert 'Achenar' in ctl.view.sheet_jumps.get_sheet_data()[0]
    ctl._perform_journal_update()
    render_tables(ctl)
    assert len(ctl.view.sheet_jumps.get_sheet_data()) == 1
    assert len(ctl.view.sheet_trade.get_sheet_data()) == 1


def test_malformed_json_record_does_not_close_gui_or_lose_next_update(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    with journal.open('ab') as stream:
        stream.write(b'{"event": "CarrierLocation"\n')
    append_events(journal, event('CarrierLocation', 1, CarrierID=1, StarSystem='Achenar', BodyID=0))
    ctl.update_journals()
    render_tables(ctl)
    assert tk_root.winfo_exists()
    assert 'Achenar' in ctl.view.sheet_jumps.get_sheet_data()[0]
    assert len(ctl.view.sheet_trade.get_sheet_data()) == 1


def test_active_journal_tab_can_be_shown_and_hidden(tk_root):
    view = CarrierView(tk_root)
    for shown in (True, False, True):
        view.checkbox_show_active_journals_var.set(shown)
        view.toggle_active_journals_tab()
        assert view.tab_controller.tab(view.tab_active_journals, 'state') == ('normal' if shown else 'hidden')


def test_initial_mixed_accounts_render_separate_carriers(tk_root, tmp_path, monkeypatch):
    events = sample_events() + sample_events(fid='F2', carrier_id=2, name='Second Carrier', callsign='DEF-456')
    ctl, _ = build_app(tk_root, tmp_path, monkeypatch, events)
    render_tables(ctl)
    assert set(row[0] for row in ctl.view.sheet_jumps.get_sheet_data()) == {'Test Carrier', 'Second Carrier'}
    assert len(ctl.view.sheet_trade.get_sheet_data()) == 2
    # Identity is ambiguous in a shared file; the view must not invent an owner.
    assert all(ctl.model.get_cmdr_name(cid) is None for cid in ctl.model.sorted_ids_display())
    assert all(row[1] not in ('Commander F1', 'Commander F2') for row in ctl.view.sheet_cmdr.get_sheet_data())


def test_append_from_second_instance_does_not_duplicate_records_in_gui(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    append_events(journal, *sample_events(fid='F2', carrier_id=2, name='Second Carrier', callsign='DEF-456'))
    for _ in range(3):
        ctl._perform_journal_update()
        render_tables(ctl)
    assert len(ctl.view.sheet_jumps.get_sheet_data()) == 2
    assert len(ctl.view.sheet_trade.get_sheet_data()) == 2
    assert len(ctl.model.journal_reader.get_items()[4]) == 2


def test_damaged_utf8_is_ignored_without_closing_gui(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    # A deleted byte in a multibyte name must not prevent later valid records.
    with journal.open('ab') as stream:
        stream.write(b'{"event":"Music","MusicTrack":"caf\xc3"}\n')
    append_events(journal, event('CarrierLocation', 1, CarrierID=1, StarSystem='Achenar', BodyID=0))
    # Record the cancellation route without actually destroying the fixture root.
    error_dialog = Mock(return_value=False)
    monkeypatch.setattr(ctl.view, 'show_message_box_askretrycancel', error_dialog)
    closed = Mock()
    ctl.view.root = SimpleNamespace(after=tk_root.after, destroy=closed)
    ctl.update_journals()
    error_dialog.assert_not_called()
    closed.assert_not_called()
    render_tables(ctl)
    assert 'Achenar' in ctl.view.sheet_jumps.get_sheet_data()[0]


def test_missing_journal_keeps_gui_open_and_recovers_when_file_returns(tk_root, tmp_path, monkeypatch):
    ctl, journal = build_app(tk_root, tmp_path, monkeypatch)
    render_tables(ctl)
    original = journal.read_bytes()
    journal.unlink()
    error_dialog = Mock(return_value=False)
    monkeypatch.setattr(ctl.view, 'show_message_box_askretrycancel', error_dialog)
    closed = Mock()
    ctl.view.root = SimpleNamespace(after=tk_root.after, destroy=closed)
    ctl.update_journals()
    closed.assert_not_called()
    journal.write_bytes(original)
    append_events(journal, event('CarrierLocation', 1, CarrierID=1, StarSystem='Achenar', BodyID=0))
    ctl.update_journals()
    render_tables(ctl)
    assert 'Achenar' in ctl.view.sheet_jumps.get_sheet_data()[0]
