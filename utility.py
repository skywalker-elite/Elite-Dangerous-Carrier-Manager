import sys, os
from datetime import datetime
import re
from numpy import datetime64
import requests
from packaging import version

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