# Known test defects

These diagnostics assert intended behavior against unchanged application code. They are separate from required regression checks and deliberately fail while the defects remain. All journal inputs, credentials, and service responses are synthetic.

Run all cases in your current environment with `python -m pytest -m known_defect -vv`, or select a reproduction below with `python -m pytest <file>::<function> -vv`. Only on a Linux host without a display, prefix commands with `xvfb-run -a`. Parameterized cases are included automatically. See [the testing guide](TESTING.md) for CI reporting and promotion after fixes.

Severity describes the consequence: High means startup/update failure or incorrect account/state attribution; Medium means a broken supporting workflow or inconsistent output; Low means a presentation defect. A diagnostic failure is evidence of the stated case, not proof that unrelated failure modes are handled.

## Journal and model diagnostics

These failures were reproduced on the unchanged implementation with synthetic journals and a fixed clock. All tests below use ordinary assertions; a failed assertion or uncaught exception is a failing diagnostic. Commands use pytest's `-k` selection to include all named parameter cases. Source references are relative to the repository root.

| ID / severity | Reproduction (test function) | Expected behavior | Observed behavior / source |
| --- | --- | --- | --- |
| **JR-001 / High** | `tests/test_journal_resilience.py::test_structurally_damaged_record_does_not_block_next_valid_record` | Skip non-object JSON, missing event names, missing FID, or missing CarrierID and consume the following valid fuel update. | `_parse_items` indexes unchecked JSON values and required keys: `TypeError` or `KeyError`; the next valid record cannot be consumed. `model.py:183`–202. |
| **JR-002 / High** | `tests/test_journal_resilience.py::test_deleted_utf8_byte_does_not_abort_whole_file` | A deleted byte in a completed UTF-8 record must not prevent valid records before/after it from loading. | `UnicodeDecodeError` escapes; only JSON syntax errors are caught. Reproduced before, between, and after healthy events. `model.py:120`–133. |
| **JR-003 / High** | `tests/test_journal_resilience.py::test_invalid_timestamp_does_not_discard_valid_carrier_state` | Ignore a damaged event with a non-string, invalid calendar date, or malformed timestamp; preserve the valid stats snapshot. | Sorting calls `_timestamp_key` and aborts model construction with `ValueError`. Direct timestamp-validator rejection remains intentional; ingestion needs recovery. `model.py:227`–240, 316. |
| **JR-004 / High** | `tests/test_journal_resilience.py::test_broken_nested_stats_preserve_previous_snapshot` | Retain usable stats when a later record has malformed finance/space data; tables remain renderable. | `process_stats` raises `TypeError`/`KeyError` on nested values; a nonnumeric cargo value raises `ValueError` when the misc table is rendered. `model.py:395`–420, 966–969. |
| **JR-005 / High** | `tests/test_journal_resilience.py::test_missing_stats_recovers_when_stats_event_arrives`, `test_partial_first_record_waits_for_completion_without_crashing` | A session lacking CarrierStats or containing only a partially written first record should wait for later data and recover. | `read_journals` asserts that stats exist, including on the initial reader poll and during model construction. `model.py:109`. |
| **JR-006 / High** | `tests/test_journal_resilience.py::test_unavailable_journal_directory_recovers_when_file_arrives`, `test_disappearing_file_does_not_block_healthy_journal` | Continue with healthy paths, tolerate empty/unavailable paths or a file removed before opening, and accept journals arriving later. | Empty directories assert; missing directories/files raise `FileNotFoundError`; a healthy directory alongside the missing one does not save the read. `model.py:81`–87, 120. |
| **JR-007 / High** | `tests/test_journal_resilience.py::test_interleaved_append_batches_preserve_established_owners` | Ownership established independently for carrier 2/F2 must survive a stats record in a shared file last identified as F1. | Carrier 2 is reassigned to F1 by the batch-level FID, contaminating account association. `model.py:183`–202. |
| **JR-008 / High** | `tests/test_journal_resilience.py::test_switching_accounts_in_shared_file_does_not_duplicate_consumption` | After appending F2's session to F1's file, repeated polls consume both sessions exactly once. | A conflicting appended Commander prevents the known-file position from advancing correctly; repeated polling grows two stats records to five. `model.py:76`–103, 156–177. |
| **JR-009 / High** | `tests/test_journal_resilience.py::test_one_instance_shutdown_does_not_hide_other_instance_appends` | One instance shutting down in a shared file must not hide another instance's subsequent fuel update. | The file is treated as inactive and no longer polled; fuel remains 500 instead of 777. `model.py:99`–101, 224. |
| **JR-010 / Medium** | `tests/test_journal_resilience.py::test_missing_commander_in_older_running_journal_still_accepts_carrier_updates` | A running journal without Commander should still accept carrier-ID updates without guessing ownership. | A filename older than one hour is dropped from unknown-FID monitoring; later fuel updates are ignored (500 instead of 800). `model.py:102`–103, 167–173. |
| **MD-001 / Medium** | `tests/test_model.py::test_trade_history_survives_incremental_updates` | A replacement trade order updates the active order while retaining both historical orders. | Incremental processing replaces `trade_history` with only the latest batch (one row instead of two). `model.py:519`–535. |
| **MD-002 / High** | `tests/test_model.py::test_missing_trade_events_have_empty_history` | No trade events should produce an empty history and no largest order. | Empty active-trade rendering works, but `get_trade_history` raises `KeyError: trade_history`. `model.py:539`–585, 1193–1195. |
| **MD-004 / High** | `tests/test_model.py::test_largest_order_when_capacity_filter_removes_every_row` | Return `None` when the existing capacity filter removes every candidate order. | Accessing `.iloc[0]` after filtering raises `IndexError`. The current exclusive capacity cutoff is characterized by mandatory tests; changing that business rule is not required. `model.py:1132`–1135. |
| **MD-005 / High** | `tests/test_model.py::test_recent_jump_missing_departure_time_preserves_usable_model` | A damaged recent jump lacking DepartureTime must not prevent a usable carrier model and tables. | `process_jumps` asserts `Unexpected missing jump time`. A separate regression preserves the supported historical 15-minute fallback. `model.py:475`–480. |
| **MD-006 / Medium** | `tests/test_model.py::test_initial_and_incremental_docking_permissions_agree` | A permission event newer than CarrierStats should be reflected on the initial read just as on an incremental read. | Initial processing retains `all/false` from stats instead of the later `friends/true`. `model.py:436`–441. |

Example: `python -m pytest -m known_defect tests/test_journal_resilience.py -k switching_accounts -vv`. Promote a test into mandatory regression coverage by removing only its `known_defect` marker after its production fix passes in your current environment.

## Reproduced service and settings defects

These diagnostics use ordinary assertions and intentionally fail against the current
production code. They never contact real services or modify personal settings or
credentials. Run a case with `python -m pytest tests/test_auth.py -k failed_refresh`
(substitute the test file and function below). Remove its `known_defect` marker
after the behavior is fixed and the case passes, promoting it into regression CI.

| ID | Severity | Reproduction / test ID | Expected behavior | Observed failure and relevant code |
| --- | --- | --- | --- | --- |
| SET-001 | Medium | `tests/test_settings.py::test_wrong_types_raise_structured_validation_error` (four inputs: string reminder, integer webhook, integer abbreviation entry, string section) | Reject invalid settings through `SettingsValidationError`, which callers can handle consistently. | `Settings.validate` records type mismatches but proceeds to type-specific operations before raising the structured error. Three inputs raise `TypeError`; the section input raises `AttributeError`. Locations: `settings.py:80`, `settings.py:133`, `settings.py:139`, `settings.py:145`, `settings.py:148`. |
| AUTH-001 | High | `tests/test_auth.py::test_failed_refresh_cannot_keep_expired_session_logged_in` (rejected refresh and absent refresh token) | Expired access tokens must produce a logged-out result and no authenticated user after refresh fails. | `is_logged_in()` ignores the false return from `_refresh_access()` and returns true whenever the old JWT remains set. Locations: `auth.py:357`, `auth.py:389`. |
| AUTH-002 | Medium | `tests/test_auth.py::test_oauth_error_callback_closes_server_without_worker_exception` | An OAuth denial should preserve the error result, return from the callback worker, and close the local server. | The callback replaces its result with an error-only mapping; `_run_callback_server` then indexes missing `code`, raising `KeyError`. The exception bypasses `server_close()`; the test also asserts cleanup in `finally`. Locations: `auth.py:156`, `auth.py:188`, `auth.py:195`. |
| AUTH-003 | Medium | `tests/test_auth.py::test_unauthenticated_edge_call_raises_typed_unauthorized_error` | A logged-out edge call should raise `FunctionsHttpError` with status 401 without invoking the remote function. | Production passes three positional constructor arguments, while the installed dependency accepts message and optional code. The call raises `TypeError`. Location: `auth.py:472`. |
| NOTIFY-001 | Low | `tests/test_notifications.py::test_missing_location_has_meaningful_placeholder_in_description` (plotted and completed) | Missing journal location data should display `Unknown` in both the description and location field. | The description is interpolated before fallback values are assigned, so it includes literal `None` while the location field uses `Unknown`. Locations: `discord_handler.py:67`, `discord_handler.py:74`, `discord_handler.py:79`. |

Validation on Windows / Python 3.12.7 reproduced all ten parameterized diagnostic
failures individually through their expected application failure, with no collection
or setup errors. Missing-service JSON and network exceptions tested outside these
diagnostics document the current caller-facing error contract; they do not claim
that every application caller already handles these failures.

## Startup and GUI diagnostic findings

These tests assert recovery behavior and currently fail normally. No application
code was changed to conceal or repair the failures.

| ID | Severity | Reproduction | Expected | Observed | Location |
|---|---|---|---|---|---|
| UI-001 | High | `tests/test_startup.py::test_startup_continues_with_healthy_path_when_another_is_unavailable` | Start using an available journal location when another configured location is temporarily absent. | Startup asserts every directory exists and exits before constructing the model or window. | `main.py:51`, `main()` |
| UI-002 | High | `tests/test_gui.py::test_damaged_utf8_is_ignored_without_closing_gui` | Skip a complete record with a missing UTF-8 byte, process a subsequent valid carrier location, and keep the window open. | `UnicodeDecodeError` reaches the controller's retry/cancel dialog; cancellation destroys the window and the valid update is never applied. | `model.py:131`, `JournalReader._read_journal()`; `controller.py:459`, `CarrierController.update_journals()` |
| UI-003 | High | `tests/test_gui.py::test_missing_journal_keeps_gui_open_and_recovers_when_file_returns` | Preserve displayed carrier state while a journal file is unavailable and process new activity once it returns. | An empty journal directory raises an assertion; the controller closes the window when the error dialog is cancelled. | `model.py:85`, `JournalReader.read_journals()`; `controller.py:459`, `CarrierController.update_journals()` |

`tests/test_gui.py::test_append_from_second_instance_does_not_duplicate_records_in_gui`
also reproduces **JR-008** through the controller and a real Tk view: polling a
shared file after a second account appends records repeatedly consumes those
records. The journal report owns that defect ID.

Archived tests retain route parser, route plotter autocomplete, hidden-column,
and jump-route-progress expectations for features absent from this checkout.
Applicable column-width and UI-thread scheduling coverage is retained in
`tests/`, with worker exceptions propagated to the test runner.
