# Archived tests for unavailable features

These tests reference features that are absent from this checkout. They are preserved as development references and are outside the configured `testpaths = tests` collection. They are not conditionally skipped or counted as passing coverage.

| File | Missing feature |
| --- | --- |
| `test_route_parser.py` | The `route_parser` module and Spansh route API helpers |
| `test_route_plotter_autocomplete.py` | Route plotter view/controller APIs and autocomplete constants |
| `test_jump_route_updates.py` | Route storage and route progress controller APIs |
| `test_hidden_column_widths.py` | The `hide_columns` argument to `CarrierView.update_table` |

Restore applicable cases to `tests/` when those features are present. The supported threading and column-sizing cases from the original mixed files now live in the active suite. See [testing instructions](../docs/TESTING.md).
