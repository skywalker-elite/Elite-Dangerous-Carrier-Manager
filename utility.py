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
from config import timer_slope_thresholds, SUPABASE_URL, SUPABASE_KEY
from decos import rate_limited

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
    version_current = getCurrentVersion()      
    version_latest = getLatestVersion()
    if version_latest is not None and version.parse(version_latest) > version.parse(version_current):
        return True
    # if on a prerelease, look for newer prereleases
    elif version.parse(version_current).is_prerelease:
        version_latest = getLatestPrereleaseVersion()
        if version_latest is not None and version.parse(version_latest) > version.parse(version_current):
            return True
    return False

def getLatestVersion() -> str|None:
    try:
        response = requests.get('https://api.github.com/repos/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases/latest')
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f'Error while checking update: {e}')
        return None
    latest_version = response.json()['name'].split()[1]
    return latest_version

def isOnPrerelease() -> bool:
    current = getCurrentVersion()
    parsed_current = version.parse(current)
    return parsed_current.is_prerelease

@rate_limited(max_calls=1, period=60)
def getLatestPrereleaseVersion() -> str|None:
    """
    Fetch all prerelease tags of the same major.minor as the current version
    and return the highest prerelease.
    """
    try:
        resp = requests.get(
            'https://api.github.com/repos/skywalker-elite/Elite-Dangerous-Carrier-Manager/releases'
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f'Error checking prerelease updates: {e}')
        return None

    # determine target major.minor
    current = getCurrentVersion()
    parsed_current = version.parse(current)
    target_major = parsed_current.major
    target_minor = parsed_current.minor

    pre_versions = []
    for rel in resp.json():
        if rel.get('prerelease'):
            name = rel.get('name', '')
            tag = name.split()[1] if ' ' in name else name
            clean = tag
            try:
                parsed = version.parse(clean)
            except Exception:
                continue
            if parsed.is_prerelease and parsed.major == target_major and parsed.minor == target_minor:
                pre_versions.append(tag)

    if not pre_versions:
        return None

    # return the highest semver prerelease of the same major.minor
    return max(pre_versions, key=lambda t: version.parse(t))

def getPrereleaseUpdateVersion() -> str|None:
    return max([getLatestPrereleaseVersion(), getLatestVersion()], key=lambda t: version.parse(t))

def getCurrentVersion() -> str:
    with open(getResourcePath('VERSION'), 'r') as f:
        return f.readline().strip()

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

@rate_limited(max_calls=10, period=60)
def getExpectedJumpTimer() -> tuple[str|None, int|None, datetime|None, datetime|None, float|None]:
    response = requests.post(f'{SUPABASE_URL}/rest/v1/rpc/jump_timer_stats_cached', headers={
        'content-type': 'application/json',
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}'
    })
    if response.status_code == 200:
        data = response.json()[0]
        if data is None:
            return None, None, None, None, None
        avg_timer = data.get('avg', None)
        count = data.get('cnt', None)
        earliest = data.get('earliest', None)
        latest = data.get('latest', None)
        slope = data.get('slope', None)
        if avg_timer is not None:
            h, m, s = getHMS(int(avg_timer))
            avg_timer = f'{h:02} h {m:02} m {s:02} s'
        return avg_timer, count, datetime.fromisoformat(earliest) if earliest else None, datetime.fromisoformat(latest) if latest else None, slope
    return None, None, None, None, None

def getHumanizedExpectedJumpTimer() -> str:
    avg_timer, count, earliest, latest, slope = getExpectedJumpTimer()
    return getTimerStatDescription(avg_timer, count, earliest, latest, slope)

def getTimerStatDescription(avg_timer:str|None, count:int|None, earliest:datetime|None, latest:datetime|None, slope:float|None) -> str:
    # Disable slope description for now, not enough data to be useful
    # return '\n'.join([generateHumanizedExpectedJumpTimer(avg_timer, count, earliest, latest), generateTimerSlopeDescription(slope)])
    return generateHumanizedExpectedJumpTimer(avg_timer, count, earliest, latest)

def generateHumanizedExpectedJumpTimer(avg_timer:str|None, count:int|None, earliest:datetime|None, latest:datetime|None) -> str:
    if avg_timer is None:
        return 'No recent timer reported'
    else:
        earliest_str = naturaltime(earliest) if earliest else 'N/A'
        latest_str = naturaltime(latest) if latest else 'N/A'
        return f'Average jump timer: {avg_timer} based on {count} report(s) from {earliest_str} to {latest_str}'
    
def generateTimerSlopeDescription(slope:float|None) -> str:
    return '' # Disable slope description for now, not enough data to be useful
    if slope is None:
        return 'No trend data available'
    elif slope > timer_slope_thresholds['surge']:
        return 'Timer is surging'
    elif slope > timer_slope_thresholds['climb']:
        return 'Timer is climbing'
    elif slope < timer_slope_thresholds['down']:
        return 'Timer is declining'
    else:
        return 'Timer is stable'

if __name__ == '__main__':
    print(getHumanizedExpectedJumpTimer())