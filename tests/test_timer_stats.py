"""Stats polling survives transient failures without losing the last good result."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

import controller as module
import utility
from controller import CarrierController
from decos import rate_limited


def response(payload, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode('utf-8')
    return result


def stats_payload(count):
    return [{'avg': 900, 'cnt': count, 'earliest': '2026-01-01T01:00:00+00:00',
             'latest': '2026-01-01T02:00:00+00:00', 'slope': None, 'trend': 'Climb'}]


class StopPolling(BaseException):
    """Stop the infinite loop from the fake sleep, after checking each refresh."""


@pytest.mark.parametrize('failure,empty', [
    pytest.param(lambda: requests.ConnectionError('connection reset'), False, id='connection-reset'),
    pytest.param(lambda: requests.ConnectTimeout('connect timeout'), False, id='connect-timeout'),
    pytest.param(lambda: requests.ReadTimeout('read timeout'), False, id='read-timeout'),
    pytest.param(lambda: response({'error': 'unavailable'}, 503), False, id='http-error'),
    pytest.param(lambda: response([]), True, id='empty-response'),
    pytest.param(lambda: response([None]), True, id='null-row'),
    pytest.param(lambda: response([{'latest': 'invalid date'}]), False, id='invalid-timestamp'),
    pytest.param(lambda: response([{'avg': 'invalid number'}]), False, id='invalid-average'),
    pytest.param(lambda: response({'avg': 900}), False, id='invalid-response-shape'),
    pytest.param(lambda: response([42]), False, id='invalid-row-shape'),
])
def test_polling_recovers_after_bad_fetch(monkeypatch, capsys, failure, empty):
    assert_polling_recovers(monkeypatch, capsys, failure(), empty)


def test_polling_recovers_after_invalid_json(monkeypatch, capsys):
    invalid = response(None)
    invalid._content = b'not json'
    assert_polling_recovers(monkeypatch, capsys, invalid, empty=False)


def assert_polling_recovers(monkeypatch, capsys, failure, empty):
    ctl = CarrierController.__new__(CarrierController)
    ctl.timer_stats = dict(avg_timer=None, count=0, earliest=None, latest=None, slope=None, trend=None)
    post = Mock(side_effect=[response(stats_payload(4)), failure, response(stats_payload(5))])
    monkeypatch.setattr(utility, 'HTTP_SESSION', SimpleNamespace(post=post))
    # Fresh decorator state uses the real rate limiter without depending on other tests.
    fetch = rate_limited(max_calls=10, period=60)(utility.getExpectedJumpTimer.__wrapped__)
    monkeypatch.setattr(module, 'getExpectedJumpTimer', fetch)
    snapshots = []

    def sleep(seconds):
        assert seconds == module.UPDATE_INTERVAL_TIMER_STATS / 1000
        snapshots.append(ctl.timer_stats.copy())
        if len(snapshots) == 3:
            raise StopPolling()

    monkeypatch.setattr(module, 'time', SimpleNamespace(sleep=sleep))
    with pytest.raises(StopPolling):
        ctl.update_timer_stat_loop()

    assert post.call_count == 3
    assert snapshots[0]['count'] == 4
    assert snapshots[0]['trend'] == 'Climb'
    if empty:
        assert all(value is None for value in snapshots[1].values())
    else:
        assert snapshots[1] == snapshots[0]
    assert snapshots[2]['count'] == 5
    assert snapshots[2]['trend'] == 'Climb'
    assert snapshots[2]['avg_timer'] == '00 h 15 m 00 s'
    assert snapshots[2]['latest'] == datetime(2026, 1, 1, 2, tzinfo=timezone.utc)
    ctl.view = SimpleNamespace(update_timer_stat=Mock())
    ctl.redraw_timer_stat()
    assert ctl.view.update_timer_stat.call_args.args[0].endswith('\nTimers are expected to go up')
    assert ('Error updating timer stats' in capsys.readouterr().out) is (not empty)
    # Timeouts must be supplied on every attempt, including the retry.
    assert all(call.kwargs['timeout'] == (5, 10) for call in post.call_args_list)


def test_repeated_failures_still_wait_between_attempts(monkeypatch, capsys):
    ctl = CarrierController.__new__(CarrierController)
    ctl.update_timer_stat = Mock(side_effect=RuntimeError('fetch failed'))
    waits = []

    def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 3:
            raise StopPolling()

    monkeypatch.setattr(module, 'time', SimpleNamespace(sleep=sleep))
    with pytest.raises(StopPolling):
        ctl.update_timer_stat_loop()
    assert ctl.update_timer_stat.call_count == 3
    assert waits == [module.UPDATE_INTERVAL_TIMER_STATS / 1000] * 3
    assert capsys.readouterr().out.count('Error updating timer stats') == 3
