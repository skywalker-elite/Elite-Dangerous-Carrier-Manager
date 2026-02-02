from datetime import timedelta
from sys import platform

WINDOW_SIZE = "1080x420"
WINDOW_SIZE_TIMER = "300x120"

CD = timedelta(minutes=4, seconds=50)
CD_cancel = timedelta(minutes=1)
PADLOCK = timedelta(minutes=3, seconds=20)
JUMPLOCK = timedelta(minutes=10)
PLOT_REMIND = timedelta(minutes=2)
PLOT_WARN = timedelta(seconds=10)

TIME_SKEW_WARN_CD = timedelta(hours=1)

UPDATE_INTERVAL = 500
UPDATE_INTERVAL_TIMER_STATS = 1000 * 30  # 30 seconds
REDRAW_INTERVAL_FAST = 250
REDRAW_INTERVAL_SLOW = 1000
REMIND_INTERVAL = 500
SAVE_CACHE_INTERVAL = 1000 * 60 * 5  # 5 minutes

AVG_JUMP_CAL_WINDOW = 8

ASSUME_DECCOM_AFTER = timedelta(weeks=2)

ladder_systems = {
    'Gali': 'N16',
    'Wregoe TO-C b56-0': 'N15B',
    'Wregoe ZE-B c28-2': 'N15',
    'Wregoe OP-D b58-0': 'N14',
    'Plaa Trua QL-B c27-0': 'N13',
    'Plaa Trua WQ-C d13-0': 'N12',
    'HD 107865': 'N11',
    'HD 105548': 'N10',
    'HD 104785': 'N9',
    'HD 102000': 'N8',
    'HD 102779': 'N7',
    'HD 104392': 'N6',
    'HIP 56843': 'N5',
    'HIP 57478': 'N4',
    'HIP 57784': 'N3',
    'HD 104495': 'N2',
    'HD 105341': 'N1',
    'HIP 58832': 'N0'
 }

test_trade_data = {
    'trade_type': 'load',
    'trading_type': 'loading',
    'to_from': 'from',
    'carrier_name': 'P.T.N. Carrier Name',
    'carrier_callsign': 'PTN-123',
    'commodity': 'Gold',
    'system': 'Sol',
    'station': 'Abraham Lincoln',
    'profit': 15,
    'pad_size': 'Large',
    'pad_size_short': 'L',
    'demand_supply': 'demand',
    'amount': 22,
}

test_wine_unload_data = {
    'carrier_callsign': 'PTN-123',
    'planetary_body': 'Star',
}

font_sizes = {
    'amerain': 5 if platform != 'darwin' else 7,
    'tiny': 7 if platform != 'darwin' else 9,
    'small': 9 if platform != 'darwin' else 11,
    'normal': 11 if platform != 'darwin' else 13,
    'large': 13 if platform != 'darwin' else 15,
    'huge': 15 if platform != 'darwin' else 17,
    'giant': 17 if platform != 'darwin' else 19,
    'colossal': 19 if platform != 'darwin' else 21,
    'capital class signature detected': 21 if platform != 'darwin' else 23,
}

timer_slope_thresholds = {
'surge': 5e-10,
'climb': 1e-10,
'down': -5e-12
}

# --- Tooltip Configuration ---
TOOLTIP_HOVER_DELAY = 500
TOOLTIP_BACKGROUND = "#1c1c1c"
TOOLTIP_FOREGROUND = '#ffffff'

# --- Supabase Configuration ---
SUPABASE_URL = "https://ujpdxqvevfxjivvnlzds.supabase.co"
SUPABASE_KEY = "sb_publishable_W7XhQ246tT6rJipPKDMekQ_fOmMoIi2"
LOCAL_PORT = 58832
REDIRECT_URL = f"http://127.0.0.1:{LOCAL_PORT}/callback"