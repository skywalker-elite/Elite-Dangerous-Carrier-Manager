import unittest
from queue import Queue
from unittest.mock import patch

from controller import AUTOCOMPLETE_DEBOUNCE_MS, CarrierController
from view import COMBOBOX_LIST_FOCUS_DELAY_MS, RoutePlotterView


class FakeRoot:
    def __init__(self):
        self.after_calls = []
        self.cancelled = []

    def after(self, delay, callback):
        after_id = f'after-{len(self.after_calls)}'
        self.after_calls.append((delay, callback, after_id))
        return after_id

    def after_cancel(self, after_id):
        self.cancelled.append(after_id)


class FakeRoutePlotter:
    def __init__(self):
        self.suggestion_updates = []
        self.selected_systems = []
        self.cleared_systems = []
        self.plot_route_enabled = []
        self.system_names = {'start': 'Sol', 'end': ''}
        self.closed = False

    def set_system_suggestions(self, field, system_names):
        self.suggestion_updates.append((field, system_names))

    def get_system_name(self, field):
        return self.system_names[field]

    def select_system(self, field, system_name):
        self.system_names[field] = system_name
        self.selected_systems.append((field, system_name))

    def clear_system(self, field):
        self.system_names[field] = ''
        self.cleared_systems.append(field)

    def set_plot_route_enabled(self, enabled):
        self.plot_route_enabled.append(enabled)

    def close(self):
        self.closed = True


class FakeAppView:
    def __init__(self):
        self.warnings = []
        self.infos = []
        self.progress_dialogs = []

    def show_message_box_warning(self, title, message):
        self.warnings.append((title, message))

    def show_message_box_info(self, title, message):
        self.infos.append((title, message))

    def show_indeterminate_progress_bar(self, title, message):
        progress_window = FakeProgressWindow()
        progress_bar = FakeProgressBar()
        self.progress_dialogs.append((title, message, progress_window, progress_bar))
        return progress_window, progress_bar


class FakeModel:
    def get_total_capacity(self, carrier_id):
        return 25000


class FakeProgressWindow:
    def __init__(self):
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


class FakeProgressBar:
    def __init__(self):
        self.stopped = False

    def stop(self):
        self.stopped = True


class FakeRouteView:
    def __init__(self):
        self.popup = self
        self.focus_calls = 0

    def focus_set(self):
        self.focus_calls += 1


class FakePopup:
    def __init__(self):
        self.after_calls = []
        self.cancelled = []

    def after(self, delay, callback):
        after_id = f'after-{len(self.after_calls)}'
        self.after_calls.append((delay, callback, after_id))
        return after_id

    def after_cancel(self, after_id):
        self.cancelled.append(after_id)

    def after_idle(self, callback):
        callback()

    def register(self, callback):
        self.registered_callback = callback
        return 'select_system_suggestion'


class FakeTk:
    def __init__(self):
        self.calls = []
        self.eval_calls = []

    def call(self, *args):
        self.calls.append(args)
        if args[0] == 'ttk::combobox::PopdownWindow':
            return f'{args[1]}.popdown'
        if args[0].endswith('.f.l') and args[1:] == ('nearest', '42'):
            return '1'
        if args[0] == 'bind' and len(args) == 3:
            return ''
        return None

    def eval(self, script):
        self.eval_calls.append(script)


class FakeCombobox:
    def __init__(self, path):
        self.path = path
        self.tk = FakeTk()
        self.values = None
        self.focus_calls = 0
        self.current_index = None
        self.selection_range_calls = []
        self.icursor_calls = []
        self.events = []

    def __str__(self):
        return self.path

    def __setitem__(self, key, value):
        if key != 'values':
            raise KeyError(key)
        self.values = value

    def focus_set(self):
        self.focus_calls += 1

    def focus_force(self):
        self.focus_calls += 1

    def current(self, index):
        self.current_index = index

    def selection_range(self, start, end):
        self.selection_range_calls.append((start, end))

    def icursor(self, index):
        self.icursor_calls.append(index)

    def event_generate(self, event):
        self.events.append(event)


def create_controller():
    controller = CarrierController.__new__(CarrierController)
    controller.root = FakeRoot()
    controller._ui_callbacks = Queue()
    controller.route_plotter_views = {1: FakeRoutePlotter()}
    controller._route_plotter_autocomplete_request_ids = {}
    controller._route_plotter_autocomplete_after_ids = {}
    controller._route_plotter_system_search_results = {}
    controller._route_plotter_selected_systems = {}
    controller._route_plotter_plotting = set()
    controller._route_import_progress_windows = {}
    controller.route_views = {1: FakeRouteView()}
    controller.view = FakeAppView()
    controller.model = FakeModel()
    return controller


def create_route_plotter_view():
    route_plotter = RoutePlotterView.__new__(RoutePlotterView)
    route_plotter.cbox_start_system = FakeCombobox('.start')
    route_plotter.cbox_end_system = FakeCombobox('.end')
    route_plotter.popup = FakePopup()
    route_plotter._suggestion_combobox = None
    route_plotter._suggestion_listbox = None
    route_plotter._suggestion_listbox_focus_out_binding = None
    route_plotter._suggestion_listbox_focus_in_binding = None
    route_plotter._suggestion_listbox_button_press_binding = None
    route_plotter._ignore_next_suggestion_focus_out = False
    route_plotter._select_system_suggestion_command = 'select_system_suggestion'
    route_plotter.on_system_selected = lambda *_: None
    route_plotter.on_plot_route = lambda *_: None
    return route_plotter


class RoutePlotterAutocompleteTests(unittest.TestCase):
    def test_current_result_updates_suggestions(self):
        controller = create_controller()
        controller.autocomplete_route_plotter_system(1, 'start', 'Sol')

        controller._show_route_plotter_system_suggestions(1, 'start', 1, [
            {'id64': 1, 'name': 'Sol'},
            {'id64': 2, 'name': 'Sola Prospect'},
        ])

        self.assertEqual(controller.route_plotter_views[1].suggestion_updates, [
            ('start', []),
            ('start', ['Sol', 'Sola Prospect']),
        ])

    def test_stale_result_is_ignored_after_input_changes(self):
        controller = create_controller()
        controller.autocomplete_route_plotter_system(1, 'start', 'Sol')
        controller.autocomplete_route_plotter_system(1, 'start', 'Achenar')

        controller._show_route_plotter_system_suggestions(1, 'start', 1, [{'id64': 1, 'name': 'Sol'}])

        self.assertEqual(controller.route_plotter_views[1].suggestion_updates, [
            ('start', []),
            ('start', []),
        ])
        self.assertEqual(controller.root.cancelled, ['after-0'])

    def test_lookup_starts_in_a_background_thread_after_debounce(self):
        controller = create_controller()

        with patch('controller.threading.Thread') as thread:
            controller.autocomplete_route_plotter_system(1, 'start', 'Sol')
            delay, callback, _ = controller.root.after_calls[0]
            callback()

        self.assertEqual(delay, AUTOCOMPLETE_DEBOUNCE_MS)
        thread.assert_called_once_with(
            target=controller._search_route_plotter_systems,
            args=(1, 'start', 1, 'Sol'),
            daemon=True,
        )
        thread.return_value.start.assert_called_once_with()

    def test_closing_route_plotter_cancels_pending_search_and_invalidates_results(self):
        controller = create_controller()
        controller.autocomplete_route_plotter_system(1, 'start', 'Sol')

        controller._close_route_plotter(1)
        controller._show_route_plotter_system_suggestions(1, 'start', 1, [{'id64': 1, 'name': 'Sol'}])

        self.assertNotIn(1, controller.route_plotter_views)
        self.assertEqual(controller.root.cancelled, ['after-0'])

    def test_view_posts_the_native_combobox_dropdown_and_restores_entry_focus(self):
        route_plotter = create_route_plotter_view()

        route_plotter.set_system_suggestions('start', ['Sol', 'Sola Prospect'])

        self.assertEqual(route_plotter.cbox_start_system.values, ['Sol', 'Sola Prospect'])
        self.assertEqual(route_plotter.cbox_start_system.tk.eval_calls, ['ttk::combobox::Post .start'])
        self.assertIn(
            ('bind', '.start.popdown.f.l', '<FocusOut>', 'break'),
            route_plotter.cbox_start_system.tk.calls,
        )
        self.assertIn(
            (
                'bind',
                '.start.popdown.f.l',
                '<FocusIn>',
                f'after {COMBOBOX_LIST_FOCUS_DELAY_MS} {{focus .start}}; bind .start.popdown.f.l <FocusIn> {{}}',
            ),
            route_plotter.cbox_start_system.tk.calls,
        )
        self.assertIn(
            (
                'bind',
                '.start.popdown.f.l',
                '<ButtonPress-1>',
                'select_system_suggestion %W %y',
            ),
            route_plotter.cbox_start_system.tk.calls,
        )
        self.assertEqual(route_plotter.cbox_start_system.focus_calls, 0)

    def test_hiding_suggestions_restores_the_native_focus_out_binding(self):
        route_plotter = create_route_plotter_view()
        route_plotter.set_system_suggestions('start', ['Sol'])

        route_plotter.hide_system_suggestions()

        self.assertIn(
            ('bind', '.start.popdown.f.l', '<FocusOut>', ''),
            route_plotter.cbox_start_system.tk.calls,
        )
        self.assertIn(
            ('bind', '.start.popdown.f.l', '<FocusIn>', ''),
            route_plotter.cbox_start_system.tk.calls,
        )
        self.assertIn(
            ('bind', '.start.popdown.f.l', '<ButtonPress-1>', ''),
            route_plotter.cbox_start_system.tk.calls,
        )
        self.assertIn(
            ('ttk::combobox::Unpost', '.start'),
            route_plotter.cbox_start_system.tk.calls,
        )

    def test_view_ignores_the_initial_native_popup_focus_transition(self):
        route_plotter = create_route_plotter_view()
        route_plotter._suggestion_combobox = route_plotter.cbox_start_system
        route_plotter._ignore_next_suggestion_focus_out = True

        route_plotter._hide_system_suggestions_on_focus_change(
            type('Event', (), {'widget': route_plotter.cbox_start_system})()
        )

        self.assertFalse(route_plotter._ignore_next_suggestion_focus_out)
        self.assertIs(route_plotter._suggestion_combobox, route_plotter.cbox_start_system)

    def test_view_commits_the_clicked_suggestion_through_its_callback(self):
        route_plotter = create_route_plotter_view()
        route_plotter._suggestion_combobox = route_plotter.cbox_start_system
        route_plotter._suggestion_listbox = '.start.popdown.f.l'

        result = route_plotter._select_system_suggestion('.start.popdown.f.l', '42')

        self.assertEqual(result, 'break')
        self.assertEqual(route_plotter.cbox_start_system.current_index, 1)
        self.assertEqual(route_plotter.cbox_start_system.selection_range_calls, [(0, 'end')])
        self.assertEqual(route_plotter.cbox_start_system.icursor_calls, ['end'])
        self.assertEqual(route_plotter.cbox_start_system.events, ['<<ComboboxSelected>>'])

    def test_selected_system_keeps_its_id64_and_enables_plotting(self):
        controller = create_controller()
        controller._route_plotter_system_search_results = {
            (1, 'start'): {'Sol': {'id64': 10477373803, 'name': 'Sol'}},
            (1, 'end'): {'Achenar': {'id64': 161007389, 'name': 'Achenar'}},
        }

        controller.select_route_plotter_system(1, 'start', 'Sol')
        controller.select_route_plotter_system(1, 'end', 'Achenar')

        self.assertEqual(controller._route_plotter_selected_systems[(1, 'start')]['id64'], 10477373803)
        self.assertEqual(controller._route_plotter_selected_systems[(1, 'end')]['id64'], 161007389)
        self.assertEqual(controller.route_plotter_views[1].plot_route_enabled, [False, True])

    def test_initial_start_system_selects_an_exact_spansh_match(self):
        controller = create_controller()

        controller._route_plotter_autocomplete_request_ids[(1, 'start')] = 1
        controller._show_route_plotter_system_suggestions(1, 'start', 1, [
            {'id64': 10477373803, 'name': 'Sol'},
            {'id64': 1, 'name': 'Solati'},
        ], True)

        self.assertEqual(controller.route_plotter_views[1].selected_systems, [('start', 'Sol')])

    def test_initial_start_system_is_cleared_when_spansh_has_no_match(self):
        controller = create_controller()

        controller._route_plotter_autocomplete_request_ids[(1, 'start')] = 1
        controller._show_route_plotter_system_suggestions(1, 'start', 1, [], True)

        self.assertEqual(controller.route_plotter_views[1].cleared_systems, ['start'])
        self.assertEqual(controller.view.warnings, [
            ('System not found', 'Sol is not available in Spansh and has been cleared.'),
        ])

    def test_plot_route_uses_selected_system_id64_values(self):
        controller = create_controller()
        controller._route_plotter_selected_systems = {
            (1, 'start'): {'id64': 10477373803, 'name': 'Sol'},
            (1, 'end'): {'id64': 161007389, 'name': 'Achenar'},
        }

        with patch('controller.threading.Thread') as thread:
            controller.button_click_plot_route(1, '5700')

        thread.assert_called_once_with(
            target=controller._plot_route,
            args=(1, '10477373803', '161007389', 25000, 5700),
            daemon=True,
        )
        thread.return_value.start.assert_called_once_with()

    def test_route_plot_worker_passes_id64_values_to_spansh(self):
        controller = create_controller()

        with patch('controller.plotRoute', return_value='route-job-id') as plot_route:
            controller._plot_route(1, '10477373803', '161007389', 25000, 5700)

        plot_route.assert_called_once_with(
            '10477373803',
            '161007389',
            25000,
            25000,
            5700,
        )

    def test_completed_route_closes_plotter_and_starts_importing(self):
        controller = create_controller()
        controller._route_plotter_plotting.add(1)

        with patch.object(controller, '_start_route_import') as start_route_import:
            controller._route_plot_submitted(1, 'route-job-id')

        self.assertTrue(controller.route_plotter_views[1].closed)
        self.assertNotIn(1, controller._route_plotter_plotting)
        self.assertEqual(controller.route_views[1].focus_calls, 1)
        start_route_import.assert_called_once_with(1, 'route-job-id')

    def test_route_import_shows_progress_and_uses_existing_storage(self):
        controller = create_controller()
        route = [['', 'Sol']]

        with patch('controller.threading.Thread') as thread:
            controller._start_route_import(1, 'route-job-id')

        self.assertEqual(controller.view.progress_dialogs[0][:2], (
            'Importing route',
            'Importing route from Spansh...',
        ))
        thread.assert_called_once_with(
            target=controller._fetch_route_for_import,
            args=(1, 'route-job-id'),
            daemon=True,
        )

        _, _, progress_window, progress_bar = controller.view.progress_dialogs[0]
        with patch.object(controller, '_store_imported_route') as store_route:
            controller._complete_route_import(1, route)

        store_route.assert_called_once_with(1, route)
        self.assertTrue(progress_bar.stopped)
        self.assertTrue(progress_window.destroyed)

if __name__ == '__main__':
    unittest.main()