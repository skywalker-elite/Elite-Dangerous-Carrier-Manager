import sys, os
import datetime
import re
from numpy import datetime64

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