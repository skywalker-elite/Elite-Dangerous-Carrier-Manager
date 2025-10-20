import sys
import tkinter as tk
from tkinter import ttk

def apply_theme_to_titlebar(win: tk.Toplevel|tk.Tk):
    if sys.platform == 'win32':
        import pywinstyles
        version = sys.getwindowsversion()

        if version.major == 10 and version.build >= 22000:
            # Set the title bar color to the background color on Windows 11 for better appearance
            pywinstyles.change_header_color(win, "#1c1c1c")# if sv_ttk.get_theme() == "dark" else "#fafafa")
        elif version.major == 10:
            pywinstyles.apply_style(win, "dark")# if sv_ttk.get_theme() == "dark" else "normal")

            # A hacky way to update the title bar's color on Windows 10 (it doesn't update instantly like on Windows 11)
            win.wm_attributes("-alpha", 0.99)
            win.wm_attributes("-alpha", 1)
    else:
        pass

def center_window(win: tk.Toplevel):
        win.update_idletasks()
        w = win.winfo_width()
        h = win.winfo_height()
        x = (win.winfo_screenwidth()  - w) // 2
        y = (win.winfo_screenheight() - h) // 2
        win.geometry(f"+{x}+{y}")

def center_window_relative_to_parent(win: tk.Toplevel, parent: tk.Tk):
    def _do_center():
        win.update_idletasks()
        parent.update_idletasks()
        w = win.winfo_width()
        h = win.winfo_height()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        win.geometry(f"+{x}+{y}")
    # wait until the window is actually mapped and all geometry is done
    win.after_idle(_do_center)

def create_dialog(root: tk.Tk, title: str) -> tuple[tk.Toplevel, ttk.Frame]:
    try:
        state = root.wm_state()
        if state == 'withdrawn' or state == 'iconic':
            root.deiconify()
    except Exception:
        try:
            state = root.state()
            if state == 'withdrawn' or state == 'iconic':
                root.deiconify()
                root.deiconify()
        except Exception:
            pass
    dialog = tk.Toplevel(root)
    dialog.transient(root)
    apply_theme_to_titlebar(dialog)
    dialog.title(title)
    frame = ttk.Frame(dialog, padding=12)
    frame.pack(fill='both', expand=True)
    return dialog, frame

def show_message_box_info(root: tk.Tk, title: str, message: str):
    root.bell()

    dialog, frame = create_dialog(root, title)

    tk.Label(frame, bitmap='info').grid(row=0, column=0, padx=8, pady=8)
    ttk.Label(frame, text=message, wraplength=400, justify='center').grid(row=0, column=1, pady=8, padx=8)
    ttk.Button(frame, text='OK', command=dialog.destroy).grid(row=1, column=0, columnspan=2, ipadx=8, padx=8, pady=(8, 0))

    dialog.attributes('-topmost', True)
    center_window_relative_to_parent(dialog, root)
    dialog.focus_set()
    root.wait_window(dialog)

def show_message_box_info_no_topmost(root: tk.Tk, title:str, message:str):
    root.bell()

    dialog, frame = create_dialog(root, title)

    tk.Label(frame, bitmap='info').grid(row=0, column=0, padx=8, pady=8)
    ttk.Label(frame, text=message, wraplength=400, justify='center').grid(row=0, column=1, pady=8, padx=8)
    ttk.Button(frame, text='OK', command=dialog.destroy).grid(row=1, column=0, columnspan=2, ipadx=8, padx=8, pady=(8, 0))

    center_window_relative_to_parent(dialog, root)
    root.wait_window(dialog)

def show_message_box_warning(root: tk.Tk, title:str, message:str):
    root.bell()

    dialog, frame = create_dialog(root, title)

    tk.Label(frame, bitmap='warning').grid(row=0, column=0, padx=8, pady=8)
    ttk.Label(frame, text=message, wraplength=400, justify='center').grid(row=0, column=1, pady=8, padx=8)
    ttk.Button(frame, text='OK', command=dialog.destroy).grid(row=1, column=0, columnspan=2, ipadx=8, padx=8, pady=(8, 0))

    dialog.attributes('-topmost', True)
    center_window_relative_to_parent(dialog, root)
    dialog.focus_set()
    root.wait_window(dialog)

def show_message_box_askyesno(root: tk.Tk, title: str, message: str) -> bool:
    root.bell()

    result = {'value': False}
    dialog, frame = create_dialog(root, title)

    tk.Label(frame, bitmap='question').grid(row=0, column=0, padx=8, pady=8)
    ttk.Label(frame, text=message, wraplength=400, justify='center').grid(row=0, column=1, pady=8, padx=8)

    frame_buttons = ttk.Frame(frame)
    frame_buttons.grid(row=1, column=0, columnspan=2, pady=(8, 0))

    def on_yes():
        result['value'] = True
        dialog.destroy()
    def on_no():
        dialog.destroy()

    ttk.Button(frame_buttons, text='Yes', command=on_yes).pack(side='left', ipadx=8, padx=8, pady=(8, 0))
    ttk.Button(frame_buttons, text='No', command=on_no).pack(side='left', ipadx=8, padx=8, pady=(8, 0))

    dialog.attributes('-topmost', True)
    center_window_relative_to_parent(dialog, root)
    dialog.focus_set()
    root.wait_window(dialog)
    return result['value']

def show_message_box_askretrycancel(root: tk.Tk, title: str, message: str) -> bool:
    root.bell()

    dialog, frame = create_dialog(root, title)
    result = False

    tk.Label(frame, bitmap='warning').grid(row=0, column=0, padx=8, pady=8)
    ttk.Label(frame, text=message, wraplength=400, justify='center').grid(row=0, column=1, pady=8, padx=8)

    frame_buttons = ttk.Frame(frame)
    frame_buttons.grid(row=1, column=0, columnspan=2, pady=(8, 0))

    def on_retry():
        nonlocal result
        result = True
        dialog.destroy()
    def on_cancel():
        dialog.destroy()

    ttk.Button(frame_buttons, text='Retry', command=on_retry).pack(side='left', ipadx=8, padx=8, pady=(8, 0))
    ttk.Button(frame_buttons, text='Cancel', command=on_cancel).pack(side='left', ipadx=8, padx=8, pady=(8, 0))

    center_window_relative_to_parent(dialog, root)
    dialog.attributes('-topmost', True)
    root.wait_window(dialog)
    return result

def show_non_blocking_info(root: tk.Tk, title:str, message:str):
    root.bell()

    dialog, frame = create_dialog(root, title)

    tk.Label(frame, bitmap='info').grid(row=0, column=0, padx=8, pady=8)
    ttk.Label(frame, text=message, wraplength=400, justify='center').grid(row=0, column=1, pady=8, padx=8)
    ttk.Button(frame, text='OK', command=dialog.destroy).grid(row=1, column=0, columnspan=2, ipadx=8, padx=8, pady=(8, 0))

    dialog.attributes('-topmost', True)
    center_window_relative_to_parent(dialog, root)
    dialog.focus_set()

def show_indeterminate_progress_bar(root: tk.Tk, title:str, message:str) -> tuple[tk.Toplevel, ttk.Progressbar]:
    progress_win = tk.Toplevel(root)
    progress_win.transient(root)
    apply_theme_to_titlebar(progress_win)
    progress_win.title(title)

    label = ttk.Label(progress_win, text=message)
    label.pack(pady=10, padx=10)
    progress_win.update_idletasks()  # Ensure the window dimensions are calculated

    progress_bar = ttk.Progressbar(progress_win, mode='indeterminate', length=progress_win.winfo_width()//2)
    progress_bar.pack(pady=10, padx=10)
    progress_bar.start(20)

    progress_win.attributes('-topmost', True)
    center_window_relative_to_parent(progress_win, root)
    progress_win.focus_set()
    return progress_win, progress_bar