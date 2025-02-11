# for bundled resorces to work
import sys, os
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)
import tkinter as tk
import sv_ttk
from controller import CarrierController
from model import CarrierModel
import pywinstyles, sys
from os import path
from config import WINDOW_SIZE

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
    # Update and close the splash screen
    try:
        import pyi_splash
        pyi_splash.update_text('Reading journals...')
        model = CarrierModel()
        pyi_splash.close()
    except ModuleNotFoundError:
        model = CarrierModel()
    root = tk.Tk()
    apply_theme_to_titlebar(root)
    sv_ttk.use_dark_theme()
    root.update()
    root.title("Elite Dangerous Carrier Manager")
    root.geometry(WINDOW_SIZE)
    photo = tk.PhotoImage(file = resource_path(os.path.join('images','EDCM.png')))
    root.wm_iconphoto(False, photo)
    root.update()
    app = CarrierController(root, model=model)
    root.mainloop()

if __name__ == "__main__":
    main()
