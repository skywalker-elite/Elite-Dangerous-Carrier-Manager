import os
import threading
from argparse import ArgumentParser
import tkinter as tk
import sv_ttk
from pystray import Icon, Menu, MenuItem
from PIL import Image
from controller import CarrierController
from model import CarrierModel
import sys
from utility import getResourcePath, getJournalPath
from config import WINDOW_SIZE

def apply_theme_to_titlebar(root):
    if sys.platform == 'win32':
        import pywinstyles
        version = sys.getwindowsversion()

        if version.major == 10 and version.build >= 22000:
            # Set the title bar color to the background color on Windows 11 for better appearance
            pywinstyles.change_header_color(root, "#1c1c1c")# if sv_ttk.get_theme() == "dark" else "#fafafa")
        elif version.major == 10:
            pywinstyles.apply_style(root, "dark")# if sv_ttk.get_theme() == "dark" else "normal")

            # A hacky way to update the title bar's color on Windows 10 (it doesn't update instantly like on Windows 11)
            root.wm_attributes("-alpha", 0.99)
            root.wm_attributes("-alpha", 1)
    else:
        pass

def main():
    parser = ArgumentParser()
    parser.add_argument("-p", "--paths",
                    nargs='+', dest="paths", default=None,
                    help="journal paths: overrides journal path(s)")
    args = parser.parse_args()
    if args.paths:
        journal_paths = args.paths
    else:
        journal_path = getJournalPath()
        journal_paths = [journal_path] if journal_path else None
    assert journal_paths is not None, f'No default journal path for platform {sys.platform}, please specify one with --paths'
    for journal_path in journal_paths:
        assert os.path.exists(journal_path), f'Journal path {journal_path} does not exist, please specify one with --paths if the default is incorrect'

    # build first, then splash, then tk root
    if sys.platform == 'darwin':
        model = CarrierModel(journal_paths)
    else:
        try:
            import pyi_splash # type: ignore
            pyi_splash.update_text('Reading journals...')
            try:
                model = CarrierModel(journal_paths)
            except Exception as e:
                pyi_splash.close()
                raise e
            else:
                pyi_splash.close()
        except ModuleNotFoundError:
            model = CarrierModel(journal_paths)
    root = tk.Tk()
    apply_theme_to_titlebar(root)
    sv_ttk.use_dark_theme()
    root.update()
    root.title("Elite Dangerous Carrier Manager")
    root.geometry(WINDOW_SIZE)
    photo = tk.PhotoImage(file=getResourcePath(os.path.join('images','EDCM.png')))
    root.wm_iconphoto(False, photo)
    root.update()

    def on_show(icon, item):
        root.after(0, root.deiconify)

    def on_quit(icon, item):
        icon.stop()
        root.after(0, root.destroy)

    def send_to_tray(*args):
        root.withdraw()
        tray_icon.visible = True

    tray_menu = Menu(
        MenuItem('Show', on_show, default=True),
        MenuItem('Quit', on_quit)
    )
    tray_icon = Icon(
        'EDCM',
        Image.open(getResourcePath(os.path.join('images','EDCM.png'))),
        'Elite Dangerous Carrier Manager',
        tray_menu,
    )
    threading.Thread(target=tray_icon.run, daemon=True).start()

    # send to tray when minimized
    root.bind('<Unmap>', lambda e: send_to_tray() if root.state() == 'iconic' else None)

    app = CarrierController(root, model=model)
    root.mainloop()

if __name__ == "__main__":
    main()
