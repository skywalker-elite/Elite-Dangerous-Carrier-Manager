import unittest
from types import SimpleNamespace
from unittest.mock import patch

import route_parser


def response(status_code, payload=None):
    return SimpleNamespace(status_code=status_code, json=lambda: payload)


class RouteParserTests(unittest.TestCase):
    def test_search_systems_returns_system_ids_and_names(self):
        payload = {
            "min_max": [
                {
                    "id64": 9896461492,
                    "name": "CO Camelopardalis",
                    "x": -68.25,
                    "y": 69.375,
                    "z": -48.78125,
                },
                {
                    "id64": 102172466946,
                    "name": "Coetl CO-B c0",
                    "x": 10895.84375,
                    "y": -956.0,
                    "z": 15608.25,
                },
            ],
            "values": ["CO Camelopardalis", "Coetl CO-B c0"],
        }

        with patch.object(route_parser, "HTTP_CLIENT") as http_client:
            http_client.get.return_value = response(200, payload)

            systems = route_parser.searchSystems.__wrapped__("co")

        http_client.get.assert_called_once_with(
            "https://spansh.co.uk/api/systems/field_values/system_names",
            params={"q": "co"},
        )
        self.assertEqual(systems, [
            {"id64": 9896461492, "name": "CO Camelopardalis"},
            {"id64": 102172466946, "name": "Coetl CO-B c0"},
        ])

    def test_get_route_retries_accepted_response_until_ready(self):
        payload = {
            "result": {
                "jumps": [{
                    "has_icy_ring": False,
                    "is_system_pristine": False,
                    "must_restock": 0,
                    "name": "Sol",
                    "distance": 0,
                    "distance_to_destination": 0,
                    "fuel_in_tank": 1000,
                    "tritium_in_market": 500,
                    "fuel_used": 0,
                }]
            }
        }

        with (
            patch.object(route_parser, "HTTP_CLIENT") as http_client,
            patch("route_parser.time.sleep") as sleep,
        ):
            http_client.get.side_effect = [response(202), response(200, payload)]

            route = route_parser.getRoute.__wrapped__("route-id")

        self.assertEqual(http_client.get.call_count, 2)
        sleep.assert_called_once_with(route_parser.ROUTE_POLL_DELAY_SECONDS)
        self.assertEqual(route.iloc[0]["System Name"], "Sol")

    def test_get_route_stops_after_maximum_accepted_responses(self):
        with (
            patch.object(route_parser, "HTTP_CLIENT") as http_client,
            patch.object(route_parser, "ROUTE_POLL_MAX_ATTEMPTS", 3),
            patch("route_parser.time.sleep") as sleep,
        ):
            http_client.get.return_value = response(202)

            with self.assertRaisesRegex(route_parser.SpanshError, "still being generated"):
                route_parser.getRoute.__wrapped__("route-id")

        self.assertEqual(http_client.get.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()