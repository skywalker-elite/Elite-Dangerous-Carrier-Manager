import requests
import humanize
from typing import Literal
from datetime import datetime, timezone, timedelta
from decos import rate_limited

class EDSMError(Exception):
    """Custom exception for EDSM API errors."""
    pass

url = 'https://www.edsm.net/api-system-v1/stations'
@rate_limited(max_calls=1, period=60)
def getStations(sys_name:str, details:bool=False) -> tuple[list[str], list[str], list[str], list[str|None]]:
    """
    Fetch station data from EDSM API.
    """
    try:
        result = requests.get(url, {'systemName': sys_name})
    except requests.exceptions.RequestException as e:
        raise EDSMError(f"Error fetching station data: {e}")
    if result.status_code != 200:
        raise EDSMError(f"Error fetching station data: {result.status_code}")
    else:
        result = result.json()
    # dirty fix with spansh to catch dodecs being classified as planetary outposts by EDSM
    try:
        spansh_stations = getStationsSpansh(result['id64'])
    except SpanshError as e:
        print(f"Error fetching station data from Spansh: {e}")
        spansh_stations = []
    for station in result['stations']:
        if station['type'] == 'Planetary Outpost':
            for spansh_station in spansh_stations:
                if station['marketId'] == spansh_station['market_id'] and spansh_station['type'] == 'Dodec Starport':
                    print(f"Reclassifying station {station['name']} from Planetary Outpost to Dodec Starport based on Spansh data")
                    station['type'] = 'Dodec Starport'
    stations = [station for station in result['stations'] if station['type'] not in ['Fleet Carrier', 'Odyssey Settlement', 'Planetary Outpost', 'Planetary Port', 'Mega ship']]
    stations = [station for station in stations if station['haveMarket']]
    station_names = [s['name'] for s in stations]
    station_types = [s['type'] for s in stations]
    station_pad_sizes = ['M' if t == 'Outpost' else 'L' for t in station_types]
    market_ids = [s['marketId'] for s in stations]
    now = datetime.now().astimezone()
    market_updated = [humanize.naturaltime(now - datetime.strptime(s['updateTime']['market'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)) if 'updateTime' in s.keys() and 'market' in s['updateTime'].keys() else None for s in stations]
    # station_dist = [s['name'] for s in stations]
    # station_names = sorted(station_names, key=station_dist)
    return stations if details else station_names, station_pad_sizes, market_ids, market_updated

@rate_limited(max_calls=10, period=30)
def getMarketCommodityInfo(market_id:str=None, system_name:str=None, station_name:str=None, commodity:str=None, commodity_name:str=None) -> dict|None:
    """
    Get market information of a commodity from EDSM API.
    """
    url = 'https://www.edsm.net/api-system-v1/stations/market'
    assert (market_id is not None) or (system_name is not None and station_name is not None), "Either market_id or system_name and station_name must be provided"
    assert commodity is not None or commodity_name is not None, "Either commodity or commodity_name must be provided"
    try:
        if market_id is not None:
            result_market = requests.get(url, {'marketId': market_id})
        else:
            result_market = requests.get(url, {'systemName': system_name, 'stationName': station_name})
    except requests.exceptions.RequestException as e:
        raise EDSMError(f"Error fetching market data: {e}")
    if result_market.status_code != 200:
        raise EDSMError(f"Error fetching market data: {result_market.status_code}")
    else:
        result_market = result_market.json()
    if commodity is not None:
        commodity_info = next((c for c in result_market['commodities'] if c['id'] == commodity), None)
    else:
        commodity_info = next((c for c in result_market['commodities'] if c['name'] == commodity_name), None)
    return commodity_info

def getStockPrice(trade_type:Literal['loading', 'unloading'], market_id:str=None, system_name:str=None, station_name:str=None, commodity:str=None, commodity_name:str=None) -> tuple[int|None, int|None]:
    """
    Get stock and price for a commodity from EDSM API.
    """
    assert trade_type in ['loading', 'unloading'], "trade_type must be either 'loading' or 'unloading'"
    commodity_info = getMarketCommodityInfo(market_id, system_name, station_name, commodity, commodity_name)
    if commodity_info is None:
        return None, None
    if trade_type == 'loading':
        stock = commodity_info['stock']
        price = commodity_info['buyPrice']
    elif trade_type == 'unloading':
        stock = commodity_info['demand']
        price = commodity_info['sellPrice']
    return stock, price

class SpanshError(Exception):
    """Custom exception for Spansh API errors."""
    pass

@rate_limited(max_calls=1, period=600)
def getStationsSpansh(system_id:int) -> list[dict]:
    """
    Get station names and types from Spansh API.
    """
    url = f'https://spansh.co.uk/api/system/{system_id}'
    try:
        result = requests.get(url)
    except requests.exceptions.RequestException as e:
        raise SpanshError(f"Error fetching station data from Spansh: {e}")
    if result.status_code != 200:
        raise SpanshError(f"Error fetching station data from Spansh: {result.status_code}")
    else:
        result = result.json()
    stations = result.get('record', {}).get('stations', [])
    return stations

if __name__ == '__main__':
    # print(getStations('sol'))
    # print(getStations('anlave', True))
    # print(getStations('Otegine', True))
    # print(getStations('Leesti', True))
    print(getStations('Brani'))
    # print(getStations('HD 105341'))
    # print(getMarketCommodityInfo(system_name='Anlave', station_name='Suri Park', commodity_name='Agronomic Treatment'))
    # print(getStockPrice('loading', system_name='Anlave', station_name='Suri Park', commodity_name='Agronomic Treatment'))
    # print(getStockPrice('loading', market_id=128127736, commodity_name='Agronomic Treatment'))
    # print(getStationsSpansh(2140781119851))
    print(getStations('Ceti Sector DL-Y d62'))