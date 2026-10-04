import tkinter as tk
import unittest
from unittest.mock import patch

from tksheet import Sheet
from view import CarrierView


class HiddenColumnWidthTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.sheet = Sheet(self.root, headers=['Name', 'Route', 'System', 'Timer'])
        self.view = CarrierView.__new__(CarrierView)
        self.view._column_resize_snapshots = {}

    def update(self, data, hidden=(1,)):
        self.view.update_table(self.sheet, data, hide_columns=list(hidden))

    def test_last_column_changes_with_route_hidden(self):
        self.update([['carrier', '', 'Sol', 'i' * 20]])
        narrow = self.sheet.column_width(2)
        with patch.object(self.sheet, 'column_width', wraps=self.sheet.column_width) as resize:
            self.update([['carrier', '', 'Sol', 'W' * 20]])
            resize.assert_called_once_with(2, width='text', redraw=False)
        self.assertGreater(self.sheet.column_width(2), narrow)
        self.update([['carrier', '', 'Sol', 'i' * 20]])
        self.assertEqual(self.sheet.column_width(2), narrow)

    def test_hidden_data_changes_skip_measurement_until_shown(self):
        self.update([['carrier', '', 'Sol', '00:02']])
        with patch.object(self.sheet, 'column_width', wraps=self.sheet.column_width) as resize, \
             patch.object(self.sheet, 'set_all_column_widths', wraps=self.sheet.set_all_column_widths) as resize_all:
            self.update([['carrier', 'W' * 30, 'Sol', '00:02']])
            resize.assert_not_called()
            resize_all.assert_not_called()
        self.update([['carrier', 'W' * 30, 'Sol', '00:02']], hidden=())
        wide = self.sheet.column_width(1)
        self.update([['carrier', 'i', 'Sol', '00:02']], hidden=())
        self.assertGreater(wide, self.sheet.column_width(1))

    def test_visibility_change_with_same_count_refits_columns(self):
        data = [['carrier', 'W' * 30, 'i', '00:02']]
        self.update(data, hidden=())
        route_width = self.sheet.column_width(1)
        self.update(data, hidden=(1,))
        data[0][1] = 'i'
        # Both layouts have three visible columns, but their data indexes differ.
        self.update(data, hidden=(2,))
        self.assertEqual(self.sheet.displayed_columns, [0, 1, 3])
        self.assertLess(self.sheet.column_width(1), route_width)

    def test_multiple_hidden_columns_use_data_indexes(self):
        self.update([['carrier', '', 'Sol', '00:02']], hidden=(1, 2))
        self.assertEqual(self.sheet.displayed_columns, [0, 3])
        self.update([['carrier', '', 'Sol', '00:01']], hidden=(1, 2))
        self.assertEqual(self.sheet.displayed_columns, [0, 3])


if __name__ == '__main__':
    unittest.main()
