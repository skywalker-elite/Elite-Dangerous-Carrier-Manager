import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from os import path
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


class ControllerThreadingTests(unittest.TestCase):
    def make_controller(self):
        root = ThreadBoundRoot()
        controller = CarrierController.__new__(CarrierController)
        controller.root = root
        controller.view = SimpleNamespace(root=root, show_message_box_warning=lambda *_: None)
        controller._ui_callbacks = Queue()
        return controller, root

    def test_watchdog_update_is_scheduled_by_the_ui_thread(self):
        controller, root = self.make_controller()

        with ThreadPoolExecutor(max_workers=1) as worker:
            worker.submit(controller._schedule_journal_update).result(timeout=5)

        self.assertEqual(root.after_calls, [])
        controller._drain_ui_callbacks()
        self.assertTrue(controller._journal_update_pending)
        self.assertEqual(root.after_calls[0][0], 0)

    def test_cache_reschedule_is_scheduled_by_the_ui_thread(self):
        controller, root = self.make_controller()
        controller.model = SimpleNamespace(journal_reader={'cache': 'value'})

        with TemporaryDirectory() as directory:
            cache_path = path.join(directory, 'cache.pickle')
            with ThreadPoolExecutor(max_workers=1) as worker:
                worker.submit(controller._save_cache, cache_path, True).result(timeout=5)

            self.assertTrue(path.exists(cache_path))
            self.assertEqual(root.after_calls, [])
            controller._drain_ui_callbacks()

        self.assertEqual(root.after_calls[0][0], SAVE_CACHE_INTERVAL)


