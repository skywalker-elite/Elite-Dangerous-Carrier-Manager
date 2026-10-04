"""EDSM/Spansh parsing with synthetic HTTP responses and no live service calls.

Decorated HTTP functions are unwrapped to keep cache state out of parsing tests;
the cache contract has separate deterministic coverage in test_decos.py.
"""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

import station_parser as stations


def response(payload, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://example.invalid/test"))


@pytest.fixture
def http_client(monkeypatch):
    client = SimpleNamespace(get=Mock())
    monkeypatch.setattr(stations, "HTTP_CLIENT", client)
    return client


@pytest.fixture
def station_data():
    def station(name, kind, market, has_market=True):
        return {"name": name, "type": kind, "marketId": market, "haveMarket": has_market}
    return {"id64": 123, "stations": [
        station("Main Starport", "Coriolis Starport", 1),
        station("Small Outpost", "Outpost", 2),
        station("Reclassified", "Planetary Outpost", 3),
        station("Surface", "Planetary Outpost", 4),
        station("Carrier", "Fleet Carrier", 5),
        station("No Market", "Orbis Starport", 6, False),
        station("Settlement", "Odyssey Settlement", 7),
        station("Port", "Planetary Port", 8),
        station("Megaship", "Mega ship", 9),
    ]}


def test_station_filtering_pad_sizes_and_spansh_reclassification(http_client, monkeypatch, station_data):
    http_client.get.return_value = response(station_data)
    spansh = Mock(return_value=[{"market_id": 3, "type": "Dodec Starport"}])
    monkeypatch.setattr(stations, "getStationsSpansh", spansh)
    names, pads, markets, updated = stations.getStations.__wrapped__("Synthetic System")
    assert names == ["Main Starport", "Small Outpost", "Reclassified"]
    assert pads == ["L", "M", "L"]
    assert markets == [1, 2, 3]
    assert updated == [None, None, None]
    spansh.assert_called_once_with(123)
    assert http_client.get.call_args.kwargs["params"] == {"systemName": "Synthetic System"}


def test_station_details_preserve_market_age_and_fallback(http_client, monkeypatch, station_data):
    data = deepcopy(station_data)
    data["stations"][0]["updateTime"] = {"market": "2026-01-01 12:00:00"}
    http_client.get.return_value = response(data)
    monkeypatch.setattr(stations, "getStationsSpansh", Mock(side_effect=stations.SpanshError("offline")))
    age = Mock(return_value="synthetic market age")
    monkeypatch.setattr(stations.humanize, "naturaltime", age)
    details, pads, markets, updated = stations.getStations.__wrapped__("Synthetic System", details=True)
    assert [entry["marketId"] for entry in details] == [1, 2]
    assert pads == ["L", "M"]
    assert markets == [1, 2]
    assert updated == ["synthetic market age", None]
    age.assert_called_once()


@pytest.mark.parametrize("lookup", [{"commodity": "gold"}, {"commodity_name": "Gold"}])
def test_market_lookup_by_identifier_or_name(http_client, lookup):
    commodity = {"id": "gold", "name": "Gold", "stock": 100, "demand": 200, "buyPrice": 300, "sellPrice": 400}
    http_client.get.return_value = response({"commodities": [commodity]})
    found = stations.getMarketCommodityInfo.__wrapped__(market_id=123, **lookup)
    assert found["stock"] == 100 and found["sellPrice"] == 400
    assert http_client.get.call_args.kwargs["params"] == {"marketId": 123}


def test_market_system_station_lookup_and_missing_commodity(http_client):
    http_client.get.return_value = response({"commodities": [{"id": "silver", "name": "Silver"}]})
    assert stations.getMarketCommodityInfo.__wrapped__(system_name="Sol", station_name="Lincoln", commodity="gold") is None
    assert http_client.get.call_args.kwargs["params"] == {"systemName": "Sol", "stationName": "Lincoln"}


@pytest.mark.parametrize("trade_type,expected", [("loading", (100, 300)), ("unloading", (200, 400))])
def test_stock_price_selects_trade_side(monkeypatch, trade_type, expected):
    monkeypatch.setattr(stations, "getMarketCommodityInfo", Mock(return_value={"stock": 100, "demand": 200, "buyPrice": 300, "sellPrice": 400}))
    assert stations.getStockPrice(trade_type, market_id=123, commodity="gold") == expected


def test_missing_commodity_has_no_stock_or_price(monkeypatch):
    monkeypatch.setattr(stations, "getMarketCommodityInfo", Mock(return_value=None))
    assert stations.getStockPrice("loading", market_id=123, commodity="gold") == (None, None)


@pytest.mark.parametrize("arguments", [{}, {"market_id": 123}, {"commodity": "gold"}])
def test_market_lookup_validates_required_identifiers(http_client, arguments):
    with pytest.raises(AssertionError):
        stations.getMarketCommodityInfo.__wrapped__(**arguments)
    http_client.get.assert_not_called()


@pytest.mark.parametrize("function,args,kwargs,expected_error", [
    (stations.getStations.__wrapped__, ("Sol",), {}, stations.EDSMError),
    (stations.getMarketCommodityInfo.__wrapped__, (), {"market_id": 1, "commodity": "gold"}, stations.EDSMError),
    (stations.getStationsSpansh.__wrapped__, (123,), {}, stations.SpanshError),
])
@pytest.mark.parametrize("failure", ["http", "timeout"])
def test_http_failures_have_service_specific_error(http_client, function, args, kwargs, expected_error, failure):
    if failure == "http":
        http_client.get.return_value = response({}, status=503)
    else:
        http_client.get.side_effect = httpx.ReadTimeout("synthetic timeout")
    with pytest.raises(expected_error):
        function(*args, **kwargs)


@pytest.mark.parametrize("function,args,kwargs", [
    (stations.getStations.__wrapped__, ("Sol",), {}),
    (stations.getMarketCommodityInfo.__wrapped__, (), {"market_id": 1, "commodity": "gold"}),
    (stations.getStationsSpansh.__wrapped__, (123,), {}),
])
def test_malformed_json_is_not_returned_as_valid_service_data(http_client, function, args, kwargs):
    http_client.get.return_value = httpx.Response(200, content=b'{"incomplete":', request=httpx.Request("GET", "https://example.invalid/test"))
    with pytest.raises(ValueError):
        function(*args, **kwargs)


@pytest.mark.parametrize("payload,expected", [({}, []), ({"record": {}}, []), ({"record": {"stations": [{"market_id": 5, "type": "Outpost"}]}}, [{"market_id": 5, "type": "Outpost"}])])
def test_spansh_station_list_and_missing_records(http_client, payload, expected):
    http_client.get.return_value = response(payload)
    assert stations.getStationsSpansh.__wrapped__(123) == expected
    assert http_client.get.call_args.args[0].endswith("/123")
