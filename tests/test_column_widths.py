"""Keep the existing proportional-font regressions without pixel snapshots."""
import pytest
from tksheet import Sheet
from view import CarrierView

pytestmark = pytest.mark.gui


@pytest.fixture
def table(tk_root):
    sheet = Sheet(tk_root, headers=['A', 'B'], font=('TkDefaultFont', 11, 'normal'))
    sheet.pack()
    view = CarrierView.__new__(CarrierView)
    view.root = tk_root
    view._column_resize_snapshots = {}
    return view, sheet


def test_equal_length_proportional_text_grows_and_shrinks(table):
    view, sheet = table
    view.update_table(sheet, [['i' * 20, 'unchanged']])
    narrow = sheet.column_width(0)
    view.update_table(sheet, [['W' * 20, 'unchanged']])
    wide = sheet.column_width(0)
    assert wide > narrow
    view.update_table(sheet, [['i' * 20, 'unchanged']])
    assert sheet.column_width(0) < wide


def test_identical_data_preserves_user_column_width(table):
    view, sheet = table
    rows = [['same', '00:02']]
    view.update_table(sheet, rows)
    sheet.column_width(0, width=230)
    view.update_table(sheet, rows)
    assert sheet.column_width(0) == 230
    assert sheet.get_sheet_data() == rows


def test_timer_update_preserves_other_columns(table):
    view, sheet = table
    view.update_table(sheet, [['same', '00:02']])
    sheet.column_width(0, width=230)
    view.update_table(sheet, [['same', '00:01']])
    assert sheet.column_width(0) == 230
    assert sheet.get_sheet_data()[0][1] == '00:01'


def test_headers_multiline_and_removed_rows(table):
    view, sheet = table
    view.update_table(sheet, [['x', 'y']])
    narrow = sheet.column_width(0)
    sheet.headers(['W' * 20, 'B'], redraw=False)
    view.update_table(sheet, [['x', 'y']])
    assert sheet.column_width(0) > narrow
    sheet.headers(['A', 'B'], redraw=False)
    view.update_table(sheet, [['x\n' + 'W' * 30, 'y'], ['x', 'y']])
    multiline = sheet.column_width(0)
    view.update_table(sheet, [['x', 'y']])
    assert sheet.column_width(0) < multiline


def test_column_structure_and_empty_tables(table):
    view, sheet = table
    for headers, rows in [(['A', 'B', 'C'], [['x', 'y', 'z']]),
                          (['A'], [['x']]), (['A'], []), ([], [])]:
        sheet.headers(headers, redraw=False)
        view.update_table(sheet, rows)
        assert sheet.get_sheet_data() == rows
        if headers:
            assert sheet.column_width(0) > 0


def test_font_changes_refit_without_data_change(table, monkeypatch):
    view, sheet = table
    view.update_table(sheet, [['W' * 20, 'y']])
    previous = sheet.column_width(0)
    for name in ('jumps', 'trade', 'finance', 'services', 'cmdr', 'misc', 'notes', 'active_journals'):
        setattr(view, 'sheet_' + name, sheet)
    monkeypatch.setattr('view.font_sizes', {'normal': 11, 'large': 22})
    view.set_font_size('normal', 'large')
    assert sheet.column_width(0) > previous
