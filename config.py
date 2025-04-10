from datetime import timedelta

WINDOW_SIZE = "1000x420"
WINDOW_SIZE_TIMER = "300x100"

CD = timedelta(minutes=4, seconds=50)
CD_cancel = timedelta(minutes=1)
PADLOCK = timedelta(minutes=3, seconds=20)
JUMPLOCK = timedelta(minutes=10)
REMIND = timedelta(minutes=2)

UPDATE_INTERVAL = 500
REDRAW_INTERVAL_FAST = 250
REDRAW_INTERVAL_SLOW = 1000
REMIND_INTERVAL = 1000

AVG_JUMP_CAL_WINDOW = 8

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