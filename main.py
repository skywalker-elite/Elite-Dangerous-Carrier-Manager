import os
from argparse import ArgumentParser
import tkinter as tk
import sv_ttk
from controller import CarrierController
from model import CarrierModel
import pywinstyles, sys
from utility import getResourcePath
from config import WINDOW_SIZE, JOURNAL_PATH

def apply_theme_to_titlebar(root):
    version = sys.getwindowsversion()

    if version.major == 10 and version.build >= 22000:
        # Set the title bar color to the background color on Windows 11 for better appearance
        pywinstyles.change_header_color(root, "#1c1c1c")# if sv_ttk.get_theme() == "dark" else "#fafafa")
    elif version.major == 10:
        pywinstyles.apply_style(root, "dark")# if sv_ttk.get_theme() == "dark" else "normal")

        # A hacky way to update the title bar's color on Windows 10 (it doesn't update instantly like on Windows 11)
        root.wm_attributes("-alpha", 0.99)
        root.wm_attributes("-alpha", 1)

def main():
    parser = ArgumentParser()
    parser.add_argument("-p", "--path",
                    action="store", dest="path", default=None,
                    help="journal path: overrides journal path")
    args = parser.parse_args()
    if args.path:
        journal_path = args.path
    else:
        journal_path = JOURNAL_PATH
    # Update and close the splash screen
    try:
        import pyi_splash # type: ignore
        pyi_splash.update_text('Reading journals...')
        model = CarrierModel(journal_path)
        pyi_splash.close()
    except ModuleNotFoundError:
        model = CarrierModel(journal_path)
    root = tk.Tk()
    apply_theme_to_titlebar(root)
    sv_ttk.use_dark_theme()
    root.update()
    root.title("Elite Dangerous Carrier Manager")
    root.geometry(WINDOW_SIZE)
    photo = tk.PhotoImage(file = getResourcePath(os.path.join('images','EDCM.png')))
    root.wm_iconphoto(False, photo)
    root.update()
    app = CarrierController(root, model=model)
    root.mainloop()

if __name__ == "__main__":
    main()
