"""Controller behavior with deterministic scheduling and isolated I/O."""
from queue import Queue
from types import SimpleNamespace
from unittest.mock import Mock
import pickle
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import pytest

import controller as module
from controller import CarrierController, JournalEventHandler
from config import SAVE_CACHE_INTERVAL, UPDATE_INTERVAL


class Scheduler:
    """Run only explicitly selected callbacks; assert Tk stays on its owner thread."""

    def __init__(self):
        self.owner = threading.get_ident()
        self.pending = {}
        self.next_id = 0
        self.destroyed = False

    def after(self, delay, callback, *args):
        assert threading.get_ident() == self.owner
        self.next_id += 1
        self.pending[self.next_id] = (delay, callback, args)
        return self.next_id

    def after_cancel(self, handle):
        self.pending.pop(handle, None)

    def run_delay(self, delay):
        selected = [key for key, call in self.pending.items() if call[0] == delay]
        for key in selected:
            _, callback, args = self.pending.pop(key)
            callback(*args)

    def destroy(self):
        self.destroyed = True


@pytest.fixture
def ctl():
    obj = CarrierController.__new__(CarrierController)
    obj.root = Scheduler()
    obj._ui_callbacks = Queue()
    obj.model = Mock()
    obj.view = Mock(root=obj.root)
    obj.view.show_message_box_askretrycancel.return_value = False
    return obj


@pytest.mark.parametrize('method', ['on_created', 'on_modified'])
@pytest.mark.parametrize('name,is_dir,expected', [
    ('Journal.2026-01-02T120000.01.log', False, 1),
    ('notes.csv', False, 0), ('journal.log', True, 0),
])
def test_watcher_filters_non_journals(ctl, method, name, is_dir, expected):
    ctl._schedule_journal_update = Mock()
    getattr(JournalEventHandler(ctl), method)(
        SimpleNamespace(src_path=name, is_directory=is_dir))
    assert ctl._schedule_journal_update.call_count == expected


def test_watcher_burst_coalesces_then_accepts_next_update(ctl, capsys):
    ctl.update_journals = Mock()
    with ThreadPoolExecutor(max_workers=1) as worker:
        for _ in range(5):
            worker.submit(ctl._schedule_journal_update).result(timeout=5)
    assert not ctl.root.pending
    ctl._drain_ui_callbacks()
    ctl.root.run_delay(0)
    assert ctl.update_journals.call_count == 1
    ctl.view.update_table_active_journals.assert_called_once()
    ctl._schedule_journal_update()
    ctl._drain_ui_callbacks()
    ctl.root.run_delay(0)
    assert ctl.update_journals.call_count == 2
    assert 'Error running UI callback' not in capsys.readouterr().out


def test_ui_queue_is_fifo_and_bad_callback_does_not_drop_following_work(ctl, capsys):
    calls = []

    def fail():
        raise ValueError('callback test failure')

    ctl._queue_ui_callback(calls.append, 'first')
    ctl._queue_ui_callback(fail)
    ctl._queue_ui_callback(calls.append, 'last')
    ctl._drain_ui_callbacks()
    assert calls == ['first', 'last']
    assert 'callback test failure' in capsys.readouterr().out
    assert ctl._ui_callbacks.empty()
    assert any(call[0] == 50 for call in ctl.root.pending.values())


def test_ui_dispatch_after_window_destruction_is_safe(ctl):
    ctl.root.after = Mock(side_effect=module.TclError('window destroyed'))
    ctl._drain_ui_callbacks()
    assert ctl._ui_callbacks.empty()


@pytest.mark.parametrize('retry', [True, False])
def test_journal_update_error_obeys_retry_or_cancel(ctl, retry):
    ctl.model.read_journals.side_effect = OSError('temporarily unavailable')
    ctl.view.show_message_box_askretrycancel.return_value = retry
    ctl.update_journals()
    assert ctl.root.destroyed is not retry
    ctl.view.show_message_box_askretrycancel.assert_called_once()
    if retry:
        ctl.model.read_journals.side_effect = None
        ctl.root.run_delay(UPDATE_INTERVAL)
        assert ctl.model.read_journals.call_count == 2


def test_cache_write_roundtrip_and_failure_delivery_on_ui(ctl, tmp_path):
    ctl.model.journal_reader = {'events': ['retained']}
    target = tmp_path / 'cache' / 'journal.pickle'
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(ctl._save_cache, str(target), True).result(timeout=5)
    assert pickle.loads(target.read_bytes()) == {'events': ['retained']}
    assert not ctl.root.pending
    ctl._drain_ui_callbacks()
    assert any(call[0] == SAVE_CACHE_INTERVAL for call in ctl.root.pending.values())
    with ThreadPoolExecutor(max_workers=1) as worker:
        worker.submit(ctl._save_cache, str(tmp_path), True).result(timeout=5)
    ctl.view.show_message_box_warning.assert_not_called()
    ctl._drain_ui_callbacks()
    ctl.view.show_message_box_warning.assert_called_once()


def test_cache_clear_removes_only_cache_and_reloads(ctl, tmp_path, monkeypatch):
    target = tmp_path / 'cache.pickle'
    target.write_bytes(b'old cache')
    unrelated = tmp_path / 'notes.csv'
    unrelated.write_text('important notes', encoding='utf-8')
    monkeypatch.setattr(module, 'getCachePath', lambda *args: str(target))
    ctl.reload = Mock()
    ctl.button_click_clear_cache()
    assert not target.exists()
    assert unrelated.read_text(encoding='utf-8') == 'important notes'
    ctl.reload.assert_called_once()
    ctl._drain_ui_callbacks()
    ctl.view.show_message_box_info.assert_called_once()


def test_cache_clear_missing_file_does_not_reload(ctl, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'getCachePath', lambda *args: str(tmp_path / 'absent'))
    ctl.reload = Mock()
    ctl.button_click_clear_cache()
    ctl._drain_ui_callbacks()
    ctl.reload.assert_not_called()
    ctl.view.show_message_box_info.assert_called_once()


@pytest.fixture
def notes(ctl, tmp_path, monkeypatch):
    destination = tmp_path / 'notes.csv'
    monkeypatch.setattr(module, 'getNotesPath', lambda: str(destination))
    ctl.model.sorted_ids_display.return_value = [2, 1]
    ctl.model.get_name.side_effect = {1: 'Alpha', 2: 'Beta'}.__getitem__
    ctl.model.get_callsign.side_effect = {1: 'AAA-111', 2: 'BBB-222'}.__getitem__
    ctl.model.get_id_by_callsign.side_effect = {'AAA-111': 1, 'BBB-222': 2}.get
    # A sheet fake retains edits across display and persistence operations.
    ctl.view.update_table_notes.side_effect = lambda rows: setattr(ctl.view.sheet_notes.get_sheet_data, 'return_value', rows)
    return destination


def test_notes_are_created_in_display_order_and_unicode_edits_persist(ctl, notes):
    ctl.load_notes()
    assert ctl.view.sheet_notes.get_sheet_data() == [
        ['Beta', 'BBB-222', ''], ['Alpha', 'AAA-111', '']]
    ctl.view.sheet_notes.get_sheet_data.return_value[0][2] = 'Cargo, café\nnext jump'
    ctl.save_notes()
    saved = pd.read_csv(notes).fillna('')
    assert saved['Carrier ID'].tolist() == ['BBB-222', 'AAA-111']
    assert saved['Note'].tolist() == ['Cargo, café\nnext jump', '']
    ctl.view.show_message_box_warning.assert_not_called()


def test_notes_reload_updates_name_without_losing_content(ctl, notes):
    notes.write_text('Carrier Name,Carrier ID,Note\nOld name,AAA-111,Keep this\n', encoding='utf-8')
    ctl.load_notes()
    ctl.root.run_delay(1000)
    assert pd.read_csv(notes).fillna('')['Note'].tolist() == ['', 'Keep this']
    assert ctl.view.sheet_notes.get_sheet_data()[1] == ['Alpha', 'AAA-111', 'Keep this']


@pytest.mark.parametrize('content', [
    'Wrong,Columns\n1,2\n',
    'Carrier Name,Carrier ID,Note\nUnknown,CCC-333,Retain me\n',
])
def test_invalid_notes_disable_saving_and_preserve_original_file(ctl, notes, content):
    notes.write_text(content, encoding='utf-8')
    ctl.load_notes()
    assert notes.read_text(encoding='utf-8') == content
    ctl.view.button_save_notes.configure.assert_called_with(state='disabled')
    ctl.view.update_table_notes.assert_not_called()
    ctl.view.show_message_box_warning.assert_called_once()


def test_notes_permission_error_reports_warning(ctl, notes, monkeypatch):
    ctl.view.sheet_notes.get_sheet_data.return_value = [['Alpha', 'AAA-111', 'note']]
    monkeypatch.setattr(pd.DataFrame, 'to_csv', Mock(side_effect=PermissionError('locked')))
    ctl.save_notes()
    ctl.view.show_message_box_warning.assert_called_once()


@pytest.mark.parametrize('outcome', ['success', 'cancel', 'error'])
def test_export_csv_handles_success_cancel_and_failure(ctl, tmp_path, monkeypatch, outcome):
    target = tmp_path / 'export.csv'
    monkeypatch.setattr(module.filedialog, 'asksaveasfilename', lambda **kwargs: '' if outcome == 'cancel' else str(target))
    data = pd.DataFrame({'Amount': [12], 'Commodity': ['Gold']})
    if outcome == 'error':
        monkeypatch.setattr(data, 'to_csv', Mock(side_effect=PermissionError('locked')))
    ctl.save_df_as_csv(data, 'orders.csv')
    assert target.exists() is (outcome == 'success')
    if outcome == 'success':
        assert pd.read_csv(target).to_dict('list') == {'Amount': [12], 'Commodity': ['Gold']}
        ctl.view.show_message_box_info.assert_called_once()
    elif outcome == 'error':
        ctl.view.show_message_box_warning.assert_called_once()
    else:
        ctl.view.show_message_box_info.assert_not_called()
        ctl.view.show_message_box_warning.assert_not_called()


@pytest.mark.parametrize('success', [True, False])
def test_clipboard_success_callback_only_runs_after_copy(ctl, monkeypatch, success):
    copied = Mock(side_effect=None if success else module.pyperclip.PyperclipException('unavailable'))
    monkeypatch.setattr(module.pyperclip, 'copy', copied)
    callback = Mock()
    ctl.copy_to_clipboard('Carrier ABC-123', 'Copied', 'Ready', callback)
    copied.assert_called_once_with('Carrier ABC-123')
    assert callback.call_count == int(success)
    assert ctl.view.show_message_box_info.call_count == int(success)
    assert ctl.view.show_message_box_warning.call_count == int(not success)


def test_cancelled_trade_history_does_not_fetch_history(ctl):
    ctl.model.sorted_ids_display.return_value = [1]
    ctl.view.show_dropdown_popup.return_value = None
    ctl.button_click_trade_history()
    ctl.model.get_trade_history.assert_not_called()


@pytest.mark.parametrize('rows,allow_multiple,expected', [
    ((), False, None), ((2,), False, 2), ((1, 2), False, None),
    ((1, 2), True, (1, 2)),
])
def test_row_selection_has_explicit_multiple_selection_behavior(ctl, rows, allow_multiple, expected):
    ctl.view.sheet_jumps.get_selected_rows.return_value = rows
    assert ctl.get_selected_row(allow_multiple=allow_multiple) == expected
