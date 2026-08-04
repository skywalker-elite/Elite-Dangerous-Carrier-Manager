
import httpx
import time

from decos import rate_limited
from station_parser import SpanshError


HTTP_CLIENT = httpx.Client(http2=True, timeout=30.0, follow_redirects=True)
ROUTE_POLL_DELAY_SECONDS = 3
ROUTE_POLL_MAX_ATTEMPTS = 10

@rate_limited(max_calls=1, period=3600)
def searchSystems(system_name:str) -> list[dict[str, int | str]]:
    """
    Fetch matching Spansh systems with their IDs and names.
    """
    url = 'https://spansh.co.uk/api/systems/field_values/system_names'
    try:
        result = HTTP_CLIENT.get(url, params={'q': system_name})
    except httpx.RequestError as e:
        raise SpanshError(f"Spansh request error: {e}")
    if result.status_code != 200:
        raise SpanshError(f"Spansh API error: {result.status_code}")
    else:
        result = result.json()
    return [
        {'id64': system['id64'], 'name': system['name']}
        for system in result.get('min_max', [])
    ]

@rate_limited(max_calls=1, period=60)
def plotRoute(source_id:str, destination_id:str, capacity:int, mass:int, capacity_used:int, calculate_starting_fuel:int=1) -> str:
    """
    Plot a route using Spansh API.
    """
    url = 'https://spansh.co.uk/api/fleetcarrier/route'
    data = {
        'source': source_id,
        'destinations': destination_id,
        'capacity': capacity,
        'mass': mass,
        'capacity_used': capacity_used,
        'calculate_starting_fuel': calculate_starting_fuel
    }
    try:
        result = HTTP_CLIENT.post(url, data=data)
    except httpx.RequestError as e:
        raise SpanshError(f"Spansh request error: {e}")
    if result.status_code not in [200, 202]:
        raise SpanshError(f"Spansh API error: {result.status_code}")
    else:
        print(result.text)
        result = result.json()
    return result['job']

@rate_limited(max_calls=10, period=60)
def getRoute(route_id:str) -> list:
    """
    Fetch route data from Spansh API.
    """
    for attempt in range(ROUTE_POLL_MAX_ATTEMPTS):
        try:
            result = HTTP_CLIENT.get(f"https://spansh.co.uk/api/results/{route_id}")
        except httpx.RequestError as e:
            raise SpanshError(f"Spansh request error: {e}")

        if result.status_code == 200:
            result = result.json()
            break
        elif result.status_code == 404:
            raise SpanshError(f"Spansh route not found, the route may have expired. Try refreshing the route on Spansh and copying the new URL.")
        if result.status_code != 202:
            raise SpanshError(f"Spansh API error: {result.status_code}")
        if attempt == ROUTE_POLL_MAX_ATTEMPTS - 1:
            raise SpanshError(
                f"Spansh route is still being generated after "
                f"{ROUTE_POLL_MAX_ATTEMPTS} attempts"
            )
        time.sleep(ROUTE_POLL_DELAY_SECONDS)

    result = result['result']
    jumps = result['jumps']

    res = []
    for i,jump in enumerate(jumps, start=1):
        icy_ring = ""
        if jump['has_icy_ring']:
            icy_ring = "Yes"
            if jump['is_system_pristine']:
                icy_ring = "Pristine"
        restock = ""
        restock_amount = ""
        if jump['must_restock'] != 0:
            restock = "Yes"
            restock_amount = str(jump['restock_amount'])
        res.append([
            "", 
            jump['name'],
            len(jumps)-i,
            round(jump['distance'], 2),
            round(jump['distance_to_destination'], 2),
            jump['fuel_in_tank'],
            jump['tritium_in_market'],
            jump['fuel_used'],
            icy_ring,
            restock,
            restock_amount
        ])
    return res

if __name__ == "__main__":
    try:
        route_id = '6A001EAC-8F8E-11F1-94FF-A884113854CE'
        route_data = getRoute(route_id)
        print("Route Data:")
        for jump in route_data:
            print(jump)
    except SpanshError as e:
        print(f"Error: {e}")

    source_id = "1797217323387"
    destination_id = "3238296097059"
    capacity = 25000
    mass = 25000
    capacity_used = 5700
    calculate_starting_fuel = 1

    try:
        route_id = plotRoute(source_id, destination_id, capacity, mass, capacity_used, calculate_starting_fuel)
        print(f"Route ID: {route_id}")
        route_data = getRoute(route_id)
        print("Route Data:")
        for jump in route_data:
            print(jump)
    except SpanshError as e:
        print(f"Error: {e}")

    system = searchSystems("sol")
    print("Search Systems Result:")
    print(system)

    system = searchSystems("HIP 78825")
    print("Search Systems Result:")
    print(system)