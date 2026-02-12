import os
import sys
from contextlib import contextmanager
from threading import Lock

lock = Lock()

@contextmanager
def _sanitize_for_external_programs_linux():
    """
    Per PyInstaller docs: restore LD_LIBRARY_PATH from LD_LIBRARY_PATH_ORIG or clear it
    before launching system-installed external programs.
    """
    if not (sys.platform.startswith("linux") and getattr(sys, "frozen", False)):
        yield
        return

    with lock:
        old = os.environ.get("LD_LIBRARY_PATH")
        orig = os.environ.get("LD_LIBRARY_PATH_ORIG")  # set by PyInstaller bootloader on Linux

        if orig is None:
            os.environ.pop("LD_LIBRARY_PATH", None)
        else:
            os.environ["LD_LIBRARY_PATH"] = orig

        try:
            yield
        finally:
            if old is None:
                os.environ.pop("LD_LIBRARY_PATH", None)
            else:
                os.environ["LD_LIBRARY_PATH"] = old

class Playsound3Patch:
    def __init__(self):
        self._playsound3 = self._get_playsound3()
        # preferred = ("gstreamer", "alsa") if sys.platform.startswith("linux") else None
        # self._backend = next((b for b in preferred if b in self._playsound3.AVAILABLE_BACKENDS), None)
        self._backend = self._playsound3.DEFAULT_BACKEND

    def _get_playsound3(self):
        # Import that may trigger ffplay probing
        with _sanitize_for_external_programs_linux():
            import playsound3
        return playsound3

    def play_sound(self, path: str, block: bool = True):
        return self._playsound3.playsound(path, block=block, backend=self._backend)