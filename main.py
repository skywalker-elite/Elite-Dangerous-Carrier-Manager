import os
from argparse import ArgumentParser
import tkinter as tk
import sv_ttk
from controller import CarrierController
from model import CarrierModel, JournalReader
import sys
import pickle
from utility import getResourcePath, getJournalPath, getCachePath
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

def load_journal_reader_from_cache(journal_paths: list[str]) -> JournalReader | None:
    cache_path = getCachePath(journal_paths)
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, 'rb') as f:
                jr = pickle.load(f)
            # smoke‐test: try to read journals once
            jr.read_journals()
            return jr
        except Exception:
            # something went wrong, nuke the cache
            try:
                os.remove(cache_path)
            except OSError:
                pass
    return None

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

    # Update and close the splash screen
    if sys.platform == 'darwin':
        jr = load_journal_reader_from_cache(journal_path)
        model = CarrierModel(journal_path, journal_reader=jrs)
    else:
        try:
            import pyi_splash  # type: ignore
            pyi_splash.update_text('Reading journals…')
            jr = load_journal_reader_from_cache(journal_paths)
            model = CarrierModel(journal_paths, journal_reader=jr)
            pyi_splash.close()
        except ModuleNotFoundError:
            jr = load_journal_reader_from_cache(journal_paths)
            model = CarrierModel(journal_paths, journal_reader=jr)

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
