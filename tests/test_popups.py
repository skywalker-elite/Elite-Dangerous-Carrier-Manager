"""Drive real dialogs with scheduled user actions; never wait for a person."""
import tkinter as tk
from tkinter import ttk

import pytest

import popups

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def quiet_dialogs(tk_root, monkeypatch):
    monkeypatch.setattr(tk_root, 'bell', lambda: None)
    # Native titlebar decoration is an OS boundary, not dialog behavior.
    monkeypatch.setattr(popups, 'apply_theme_to_titlebar', lambda win: None)


def descendants(widget, kind):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(descendants(child, kind))
    return found


def answer_dialog(root, show, action):
    """Surface callback failures and always close the modal wait on failure."""
    errors = []

    def interact():
        dialogs = descendants(root, tk.Toplevel)
        try:
            assert len(dialogs) == 1
            dialog = dialogs[0]
            # Flush layout/centering callbacks before destroying their window.
            root.update_idletasks()
            action(dialog)
        except BaseException as error:
            errors.append(error)
        finally:
            for dialog in dialogs:
                if dialog.winfo_exists():
                    dialog.destroy()

    root.after(0, interact)
    result = show()
    if errors:
        raise errors[0]
    assert descendants(root, tk.Toplevel) == []
    return result


def invoke_button(index):
    return lambda dialog: descendants(dialog, ttk.Button)[index].invoke()


@pytest.mark.parametrize('show', [popups.show_message_box_askyesno, popups.show_message_box_askretrycancel])
@pytest.mark.parametrize('button,expected', [(0, True), (1, False)])
def test_confirmation_buttons_return_user_choice(tk_root, show, button, expected):
    result = answer_dialog(tk_root, lambda: show(tk_root, 'Test', 'Choose an action'), invoke_button(button))
    assert result is expected
    assert tk_root.winfo_exists()


@pytest.mark.parametrize('show', [popups.show_message_box_askyesno, popups.show_message_box_askretrycancel])
def test_window_close_cancels_confirmation(tk_root, show):
    def close(dialog):
        dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))

    assert answer_dialog(tk_root, lambda: show(tk_root, 'Test', 'Choose an action'), close) is False


@pytest.mark.parametrize('show', [popups.show_message_box_info, popups.show_message_box_info_no_topmost, popups.show_message_box_warning])
def test_message_dialog_dismissal_returns_to_live_parent(tk_root, show):
    answer_dialog(tk_root, lambda: show(tk_root, 'Test', 'Information'), invoke_button(0))
    assert tk_root.winfo_exists()


@pytest.mark.parametrize('show', [popups.show_message_box_info_checkbox, popups.show_message_box_warning_checkbox])
@pytest.mark.parametrize('initial,toggle,expected', [(False, False, False), (False, True, True), (True, True, False)])
def test_checkbox_dialog_returns_final_state(tk_root, show, initial, toggle, expected):
    def choose(dialog):
        checkboxes = descendants(dialog, ttk.Checkbutton)
        assert len(checkboxes) == 1
        if toggle:
            checkboxes[0].invoke()
        invoke_button(0)(dialog)

    result = answer_dialog(tk_root, lambda: show(tk_root, 'Test', 'Information', 'Remember', initial), choose)
    assert result is expected


def test_dropdown_returns_selected_index(tk_root):
    def choose(dialog):
        dropdowns = descendants(dialog, ttk.Combobox)
        assert len(dropdowns) == 1
        dropdowns[0].current(2)
        invoke_button(0)(dialog)

    result = answer_dialog(tk_root, lambda: popups.show_dropdown_popup(tk_root, 'Test', 'Select carrier', ['Alpha', 'Beta', 'Gamma']), choose)
    assert result == 2


def test_dropdown_window_close_returns_no_selection(tk_root):
    result = answer_dialog(tk_root, lambda: popups.show_dropdown_popup(tk_root, 'Test', 'Select carrier', ['Alpha']), lambda dialog: dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW')))
    assert result is None


def test_non_blocking_info_returns_with_window_open(tk_root):
    popups.show_non_blocking_info(tk_root, 'Test', 'Information')
    dialogs = descendants(tk_root, tk.Toplevel)
    assert len(dialogs) == 1
    tk_root.update_idletasks()
    invoke_button(0)(dialogs[0])
    assert descendants(tk_root, tk.Toplevel) == []
    assert tk_root.winfo_exists()


def test_progress_window_can_be_stopped_and_closed(tk_root):
    window, progress = popups.show_indeterminate_progress_bar(tk_root, 'Test', 'Loading')
    assert window.winfo_exists()
    assert progress.master is window
    tk_root.update_idletasks()
    progress.stop()
    window.destroy()
    tk_root.update_idletasks()
    assert descendants(tk_root, tk.Toplevel) == []
    assert tk_root.winfo_exists()
