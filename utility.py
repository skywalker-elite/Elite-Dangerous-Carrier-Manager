import sys
import os
import subprocess
from datetime import datetime
import re
import threading
import functools
from numpy import datetime64
import requests
from packaging import version
import hashlib
from humanize import naturaltime
import time
from collections import deque
from functools import wraps
from os.path import join
from pathlib import Path

def getJournalPath() -> str:
    if sys.platform == 'win32':
        user_path = os.environ.get('USERPROFILE')
        return os.path.join(user_path, 'Saved Games', 'Frontier Developments', 'Elite Dangerous')
    elif sys.platform == 'linux':
        user_path = os.path.expanduser('~')
        return os.path.join(user_path, '.local', 'share', 'Steam', 'steamapps', 'compatdata', '359320', 'pfx', 'drive_c', 'users', 'steamuser', 'Saved Games', 'Frontier Developments', 'Elite Dangerous')
    else:
        return None

# for bundled resorces to work
def getResourcePath(relative_path):
    # Get absolute path to resource, works for dev and for PyInstaller
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

def getHMS(seconds):
    m, s = divmod(round(seconds), 60)
    h, m = divmod(m, 60)
    return h, m, s

def formatForSort(s:str) -> str:
    out = ''
    for si in s:
        if si.isdigit():
            out += chr(ord(si) + 49)
        else:
            out += si
    return out

def getHammerCountdown(dt:datetime64) -> str:
    unix_time = dt.astype('datetime64[s]').astype('int')
    return f'<t:{unix_time}:R>'

def checkTimerFormat(timer:str) -> bool:
    r = r'\d\d:\d\d:\d\d'
    if re.fullmatch(r, timer) is None:
        return False
    else:
        try:
            datetime.strptime(timer, '%H:%M:%S')
        except ValueError:
            return False
    return True

def isUpdateAvailable() -> bool:
    version_latest = getLatestVersion()
    version_current = getCurrentVersion()
    if version_latest is None or version.parse(version_latest) <= version.parse(version_current):
        return False
    else:
        return True

def getLatestVersion() -> str|None:
    try:
        response = requests.get('https://api.github.com/repos/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases/latest')
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f'Error while checking update: {e}')
        return None
    latest_version = response.json()['name'].split()[1]
    return latest_version

def getCurrentVersion() -> str:
    with open(getResourcePath('VERSION'), 'r') as f:
        return f.readline()
    
def open_file(filename):
    if sys.platform == "win32":
        os.startfile(filename)
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.call([opener, filename])

def getAppDir() -> str:
    if sys.platform == 'win32':
        user_path = os.environ.get('USERPROFILE')
        return os.path.join(user_path, 'AppData', 'Roaming', 'Skywalker-Elite', 'Elite Dangerous Carrier Manager')
    elif sys.platform == 'linux':
        user_path = os.path.expanduser('~')
        return os.path.join(user_path, '.config', 'Skywalker-Elite', 'Elite Dangerous Carrier Manager')
    elif sys.platform == 'darwin':
        user_path = os.path.expanduser('~')
        return os.path.join(user_path, '.config', 'Skywalker-Elite', 'Elite Dangerous Carrier Manager')
    else:
        return None

def getSettingsDir() -> str:
    if sys.platform == 'win32':
        user_path = os.environ.get('USERPROFILE')
        return os.path.join(user_path, 'AppData', 'Roaming', 'Skywalker-Elite', 'Elite Dangerous Carrier Manager')
    elif sys.platform == 'linux':
        user_path = os.path.expanduser('~')
        return os.path.join(user_path, '.config', 'Skywalker-Elite', 'Elite Dangerous Carrier Manager')
    elif sys.platform == 'darwin':
        user_path = os.path.expanduser('~')
        return os.path.join(user_path, '.config', 'Skywalker-Elite', 'Elite Dangerous Carrier Manager')
    else:
        return None

def getSettingsPath() -> str:
    settings_dir = getSettingsDir()
    if settings_dir is None:
        return None
    else:
        return os.path.join(settings_dir, 'settings.toml')

def getSettingsDefaultPath() -> str:
    return getResourcePath('settings_default.toml')

def getConfigSettingsPath() -> str:
    """
    Path to the json file where the app stores UI-driven (non-user-editable)
    settings. 
    """
    return join(getSettingsDir(), '.do_not_edit_config.json')

def getConfigSettingsDefaultPath() -> str:
    return getResourcePath('config_settings_default.json')

def hash_folder(folder_path:str, hash_obj) -> str:
    """Generate a hash for the contents of a folder."""
    for root, dirs, files in sorted(os.walk(folder_path)):
        for file_name in sorted(files):
            file_path = os.path.join(root, file_name)
            with open(file_path, 'rb') as f:
                while chunk := f.read(8192):  # Read file in chunks
                    hash_obj.update(chunk)


def getCachePath(jr_version:str, journal_paths:list[str]) -> str:
    cache_dir = getAppDir()
    if cache_dir is None:
        return None
    else:
        try:
            h = hashlib.md5()
            h.update(sys.platform.encode('utf-8'))
            for journal_path in journal_paths:
                h.update(journal_path.encode('utf-8'))
            return os.path.join(cache_dir, 'cache', f'journal_reader_{jr_version}_{h.hexdigest()}.pkl')
        except:
            return None
        
def getInfoHash(journal_timestamp:datetime, timer:int, carrierID:int) -> str:
    h = hashlib.sha256()
    h.update(journal_timestamp.isoformat().encode('utf-8'))
    h.update(str(timer).encode('utf-8'))
    h.update(str(carrierID).encode('utf-8'))
    return h.hexdigest()[:40]

def rate_limited(max_calls: int, period: float):
    """
    Decorator that allows up to max_calls per period (seconds),
    caching and returning the last result in between bursts,
    separately for each distinct (args, kwargs) combination.
    """
    state: dict = {}  # maps (args, sorted(kwargs)) -> {'times': deque, 'cache': result}

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            # build a hashable key for this call
            key = (args, tuple(sorted(kwargs.items())))
            if key not in state:
                state[key] = {'times': deque(), 'cache': None}

            record = state[key]
            times: deque[float] = record['times']

            # drop timestamps older than our window
            while times and now - times[0] > period:
                times.popleft()

            # if under limit, perform real call and update cache
            if len(times) < max_calls:
                times.append(now)
                try:
                    record['cache'] = func(*args, **kwargs)
                except Exception:
                    # on failure, keep last cache
                    pass

            return record['cache']
        return wrapper
    return decorator

def debounce(wait_seconds):
    """
    Postpone a function’s execution until wait_seconds have elapsed since
    the last call.  If the first arg has a .root, use root.after/after_cancel
    so the callback won’t fire after the window is closed.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            self = args[0] if args else None
            root = getattr(self, 'root', None)
            # use a unique attr per instance+method:
            after_attr = f'__debounce_after_id_{fn.__name__}'
            if root and hasattr(root, 'after'):
                # cancel previous
                prev = getattr(self, after_attr, None)
                if prev:
                    try:
                        root.after_cancel(prev)
                    except Exception:
                        pass
                # schedule new
                handle = root.after(int(wait_seconds * 1000), lambda: fn(*args, **kwargs))
                setattr(self, after_attr, handle)
            else:
                # fallback to threading.Timer
                timer_attr = f'__debounce_timer_{fn.__name__}'
                prev_timer = getattr(self, timer_attr, None)
                if prev_timer:
                    prev_timer.cancel()
                t = threading.Timer(wait_seconds, lambda: fn(*args, **kwargs))
                setattr(self, timer_attr, t)
                t.start()
        return wrapped
    return decorator

@rate_limited(max_calls=20, period=60)
def getExpectedJumpTimer() -> tuple[str|None, int|None, datetime|None, datetime|None]:
    response = requests.get('https://ujpdxqvevfxjivvnlzds.supabase.co/functions/v1/avg-jump-timer-stats')
    if response.status_code == 200:
        data = response.json()[0]
        if data is None:
            return None, None, None, None
        avg_timer = data.get('avg', None)
        count = data.get('cnt', None)
        earliest = data.get('earliest', None)
        latest = data.get('latest', None)
        if avg_timer is not None:
            h, m, s = getHMS(int(avg_timer))
            avg_timer = f'{h:02} h {m:02} m {s:02} s'
        return avg_timer, count, datetime.fromisoformat(earliest) if earliest else None, datetime.fromisoformat(latest) if latest else None
    return None, None, None, None

def getHumanizedExpectedJumpTimer() -> str:
    avg_timer, count, earliest, latest = getExpectedJumpTimer()
    return generateHumanizedExpectedJumpTimer(avg_timer, count, earliest, latest)

def generateHumanizedExpectedJumpTimer(avg_timer:str|None, count:int|None, earliest:datetime|None, latest:datetime|None) -> str:
    if avg_timer is None:
        return 'No recent timer reported'
    else:
        earliest_str = naturaltime(earliest) if earliest else 'N/A'
        latest_str = naturaltime(latest) if latest else 'N/A'
        return f'Average jump timer: {avg_timer} based on {count} sample(s) from {earliest_str} to {latest_str}'

if __name__ == '__main__':
    print(getHumanizedExpectedJumpTimer())