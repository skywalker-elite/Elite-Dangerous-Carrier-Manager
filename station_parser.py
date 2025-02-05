import requests

url = 'https://www.edsm.net/api-system-v1/stations'
def getStations(sys_name:str, details:bool=False):
    result = requests.get(url, {'systemName': sys_name})
    d = result.json()
    stations = [station for station in d['stations'] if station['type'] not in ['Fleet Carrier', 'Odyssey Settlement', 'Planetary Outpost', 'Planetary Port', 'Mega ship']]
    station_names = [s['name'] for s in stations]
    station_types = [s['type'] for s in stations]
    station_pad_sizes = ['M' if t == 'Outpost' else 'L' for t in station_types]
    # station_dist = [s['name'] for s in stations]
    # station_names = sorted(station_names, key=station_dist)
    return stations if details else station_names, station_pad_sizes

if __name__ == '__main__':
    print(getStations('sol'))
    print(getStations('anlave', True))
    print(getStations('Otegine', True))
    print(getStations('HD 105341'))