"""Finite real-Tk/model smoke coverage; no watchers, services or infinite loops."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock
from tkinter import ttk
import tkinter.font as tkfont

import pytest

import controller as module
import utility
from config import font_sizes
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


@pytest.fixture
def timer_app(tk_root, monkeypatch):
    """Real timer UI and bindings with background work and external I/O isolated."""
    model = Mock(journal_paths=[], dropout=True)
    model.get_data_active_journals.return_value = []
    response = Mock(status_code=200)
    response.json.return_value = []
    monkeypatch.setattr(utility, 'HTTP_SESSION', SimpleNamespace(post=Mock(return_value=response)))
    # These finite UI refreshes do not need the polling rate limiter.
    monkeypatch.setattr(utility, 'getExpectedJumpTimer', utility.getExpectedJumpTimer.__wrapped__)
    for name in ('AuthHandler', 'Observer', 'TimeChecker', 'ThreadPoolExecutor'):
        monkeypatch.setattr(module, name, Mock())
    monkeypatch.setattr(module, 'threading', SimpleNamespace(Thread=Mock()))
    for name in ('load_settings', 'update_journals', 'check_time_skew', 'set_current_version',
                 'redraw_fast', 'redraw_slow', 'load_notes', 'check_app_update',
                 'on_sign_in', 'on_sign_out', 'save_window_size_on_resize'):
        monkeypatch.setattr(CarrierController, name, Mock())
    browser = Mock()
    monkeypatch.setattr(module, 'open_new_tab', browser)
    ctl = CarrierController(tk_root, model)
    ctl.redraw_timer_stat()
    return SimpleNamespace(controller=ctl, response=response, browser=browser)


def test_timer_report_link_tracks_average_and_empty_data(timer_app):
    ctl = timer_app.controller
    view = ctl.view
    link = view.label_report_to_fdev
    assert view.label_timer_stat.cget('text') == 'No recent timer reported'
    assert not link.winfo_manager()
    for payload, expected_text, report_text in (
        ([{'avg': 3600, 'cnt': 4, 'trend': 'Climb'}],
         'Average jump timer: 01 h 00 m 00 s based on 4 report(s) from N/A to N/A\nTimers are expected to go up',
         'Report 1hr+ timers to FDev'),
        ([{'avg': 900, 'cnt': 5}],
         'Average jump timer: 00 h 15 m 00 s based on 5 report(s) from N/A to N/A', None),
        ([{'avg': None}], 'No recent timer reported', None),
        ([], 'No recent timer reported', None),
        ([{'avg': 7200, 'cnt': 6}],
         'Average jump timer: 02 h 00 m 00 s based on 6 report(s) from N/A to N/A',
         'Report 1hr+ timers to FDev'),
    ):
        timer_app.response.json.return_value = payload
        ctl.update_timer_stat()
        ctl.redraw_timer_stat()
        assert view.label_timer_stat.cget('text') == expected_text
        assert link.cget('text') == (report_text or '')
        assert link.winfo_manager() == ('pack' if report_text else '')
    timer_app.browser.assert_not_called()
    view.set_font_size('large', 'normal')
    font = tkfont.Font(root=ctl.root, font=ttk.Style(ctl.root).lookup(link.cget('style'), 'font'))
    assert font.actual('underline') == 1
    assert font.actual('size') == font_sizes['large']
    assert str(link.cget('cursor')) == 'hand2'


@pytest.mark.parametrize('activation', ['<Button-1>', '<Return>'])
def test_timer_report_link_opens_fdev_issue(timer_app, activation):
    ctl = timer_app.controller
    timer_app.response.json.return_value = [{'avg': 3600, 'cnt': 4}]
    ctl.update_timer_stat()
    ctl.redraw_timer_stat()
    ctl.root.deiconify()
    ctl.root.update()
    link = ctl.view.label_report_to_fdev
    assert link.winfo_ismapped()
    if activation == '<Return>':
        link.focus_force()
        ctl.root.update()
    link.event_generate(activation)
    ctl.root.update()
    timer_app.browser.assert_called_once_with(url='https://issues.frontierstore.net/issue-detail/72422')


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
