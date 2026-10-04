import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from os import path
from unittest.mock import patch

import pandas as pd

from config import SAVE_CACHE_INTERVAL
from controller import CarrierController


class ThreadBoundRoot:
    def __init__(self):
        self.owner_thread = threading.get_ident()
        self.after_calls = []

    def after(self, delay, callback, *args):
        if threading.get_ident() != self.owner_thread:
            raise RuntimeError('main thread is not in main loop')
        self.after_calls.append((delay, callback, args))


class ThreadBoundRouteView:
    def __init__(self):
        self.owner_thread = threading.get_ident()
        self.closed = False
        self.updates = []

    def set_data(self, data):
        if threading.get_ident() != self.owner_thread:
            raise RuntimeError('route window updated outside the UI thread')
        if self.closed:
            raise RuntimeError('route window already destroyed')
        self.updates.append(data.copy())


class JumpRouteUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.route_path = path.join(self.directory.name, 'route.csv')
        route_path_patch = patch('controller.getRoutePath', return_value=self.route_path)
        route_path_patch.start()
        self.addCleanup(route_path_patch.stop)

        self.route = pd.DataFrame({'Done': [''], 'System Name': ['Destination']})
        self.route_view = ThreadBoundRouteView()
        self.controller = CarrierController.__new__(CarrierController)
        self.controller.root = ThreadBoundRoot()
        self.controller._ui_callbacks = Queue()
        self.controller.model = SimpleNamespace(
            routes={1: {'route': self.route, 'progress': 0, 'length': len(self.route)}},
            get_callsign=lambda _: 'ABC-123',
            get_current_system=lambda _: 'Destination',
            get_previous_system=lambda _: 'Origin',
        )
        self.controller.route_views = {1: self.route_view}
        self.controller.settings = SimpleNamespace(get=lambda *args: False)
        self.controller.notification_settings = {}
        self.controller.notification_settings_carrier = {}
        self.controller.webhook_handler = None
        self.controller.webhook_handler_public = None
        self.controller.webhook_handler_carrier = {}

    def complete_jump(self):
        # Propagate worker exceptions so a failed UI call cannot silently pass.
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.controller.status_change, 1, 'jumping', 'cool_down').result(timeout=5)

    def drain_ui_callbacks(self):
        with patch('builtins.print') as output:
            self.controller._drain_ui_callbacks()
        output.assert_not_called()  # The queue must not swallow a callback failure.

    def test_jump_updates_route_and_persists_progress_on_ui_thread(self):
        self.complete_jump()

        self.assertEqual(self.controller.model.routes[1]['progress'], 0)
        self.assertEqual(self.route_view.updates, [])
        self.assertFalse(path.exists(self.route_path))

        self.drain_ui_callbacks()

        self.assertEqual(self.controller.model.routes[1]['progress'], 1)
        self.assertEqual(self.route.at[0, 'Done'], '\u2714')
        pd.testing.assert_frame_equal(self.route_view.updates[0], self.route)
        pd.testing.assert_frame_equal(pd.read_csv(self.route_path), self.route)

    def test_window_closed_before_callback_still_saves_progress(self):
        self.complete_jump()
        self.controller.route_views.pop(1)
        self.route_view.closed = True

        self.drain_ui_callbacks()

        self.assertEqual(self.route_view.updates, [])
        self.assertEqual(self.controller.model.routes[1]['progress'], 1)
        self.assertEqual(pd.read_csv(self.route_path).at[0, 'Done'], '\u2714')

    def test_reopened_window_receives_pending_update(self):
        self.complete_jump()
        self.route_view.closed = True
        replacement = ThreadBoundRouteView()
        self.controller.route_views[1] = replacement

        self.drain_ui_callbacks()

        self.assertEqual(self.route_view.updates, [])
        self.assertEqual(replacement.updates[0].at[0, 'Done'], '\u2714')

    def test_jump_after_last_route_step_is_a_noop(self):
        self.complete_jump()
        self.drain_ui_callbacks()

        with patch.object(pd.DataFrame, 'to_csv') as save:
            self.complete_jump()
            self.drain_ui_callbacks()

        save.assert_not_called()
        self.assertEqual(self.controller.model.routes[1]['progress'], 1)
        self.assertEqual(len(self.route_view.updates), 1)

    def test_empty_route_is_a_noop(self):
        self.controller.model.routes[1] = {
            'route': self.route.iloc[:0], 'progress': 0, 'length': 0,
        }

        self.complete_jump()
        self.drain_ui_callbacks()

        self.assertFalse(path.exists(self.route_path))
        self.assertEqual(self.route_view.updates, [])

    def test_jump_to_different_system_does_not_advance_route(self):
        self.controller.model.get_current_system = lambda _: 'Elsewhere'

        self.complete_jump()
        self.drain_ui_callbacks()

        self.assertEqual(self.controller.model.routes[1]['progress'], 0)
        self.assertFalse(path.exists(self.route_path))
        self.assertEqual(self.route_view.updates, [])

    def test_route_cleared_before_callback_is_not_resurrected(self):
        self.complete_jump()
        self.controller.model.routes.pop(1)

        self.drain_ui_callbacks()

        self.assertNotIn(1, self.controller.model.routes)
        self.assertFalse(path.exists(self.route_path))
        self.assertEqual(self.route_view.updates, [])

    def test_automatic_ladder_route_updates_window_on_ui_thread(self):
        self.controller.model.routes.clear()
        self.controller.model.get_current_system = lambda _: 'HIP 58832'
        self.controller.settings.get = lambda *args: True

        self.complete_jump()

        self.assertEqual(self.controller.model.routes, {})
        self.assertEqual(self.route_view.updates, [])

        self.drain_ui_callbacks()

        route_info = self.controller.model.routes[1]
        self.assertEqual(route_info['progress'], 1)
        self.assertEqual(route_info['route'].at[0, 'Done'], '\u2714')
        self.assertEqual(len(self.route_view.updates), 1)
        self.assertTrue(path.exists(self.route_path))


if __name__ == '__main__':
    unittest.main()
