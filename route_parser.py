
import httpx

from decos import rate_limited
from station_parser import SpanshError


HTTP_CLIENT = httpx.Client(http2=True, timeout=30.0, follow_redirects=True)

@rate_limited(max_calls=1, period=60)
def getRoute(route_id:str) -> list:
    """
    Fetch route data from Spansh API.
    """
    try:
        result = HTTP_CLIENT.get(f"https://www.spansh.co.uk/api/results/{route_id}")
    except httpx.RequestError as e:
        raise SpanshError(f"Spash request error: {e}")
    if result.status_code != 200:
        raise SpanshError(f"Spansh API error: {result.status_code}")
    else:
        result = result.json()
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