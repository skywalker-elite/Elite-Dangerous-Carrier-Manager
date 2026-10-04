"""Clock skew samples and warning boundaries with a deterministic clock."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import URLError

import pytest

import time_checker
from time_checker import TimeChecker


def test_selects_lowest_rtt_and_preserves_all_samples(monkeypatch):
    monotonic = iter([0.0, 0.8, 2.0, 2.2, 4.0, 4.4])
    wall = iter([101.0, 101.8, 103.0, 103.2, 105.0, 105.4])
    sleeps = []
    monkeypatch.setattr(time_checker, "time", SimpleNamespace(
        monotonic=lambda: next(monotonic), time=lambda: next(wall), sleep=sleeps.append))
    payloads = iter([b'{"unixTimestamp": 100}', b'{"unixTimestamp": 102}', b'{"unixTimestamp": 104}'])
    urlopen = Mock(side_effect=lambda *args, **kwargs: BytesIO(next(payloads)))
    monkeypatch.setattr(time_checker, "urlopen", urlopen)
    result = TimeChecker(spacing_s=0.75, timeout=2.5).measure_server_skew()
    assert len(result["all"]) == 3
    assert result["rtt_s"] == pytest.approx(0.2)
    assert result["diff_s"] == pytest.approx(0.6)
    assert result["uncertainty_s"] == pytest.approx(0.6)
    assert sleeps == [0.75, 0.75]
    assert all(call.kwargs["timeout"] == 2.5 for call in urlopen.call_args_list)


@pytest.mark.parametrize("difference,uncertainty,expected", [
    (0, 0.5, False), (1.5, 0.5, False), (1.5001, 0.5, True),
    (-1.5001, 0.5, True), (2.5, 2.0, False), (2.5001, 2.0, True),
])
def test_warning_requires_difference_beyond_threshold_and_noise(difference, uncertainty, expected):
    assert TimeChecker().should_warn(difference, uncertainty) is expected


@pytest.mark.parametrize("difference,expected,direction", [(3.0, True, "ahead"), (-3.0, True, "behind"), (0.2, False, None)])
def test_warning_result_contains_measurement_and_correct_direction(monkeypatch, difference, expected, direction):
    checker = TimeChecker()
    monkeypatch.setattr(checker, "measure_server_skew", lambda: {"diff_s": difference, "rtt_s": 0.2, "uncertainty_s": 0.6})
    warn, message = checker.check_and_warn()
    assert warn is expected
    assert f"{difference:+.2f}" in message
    if direction:
        assert direction in message


@pytest.mark.parametrize("failure", [URLError("offline"), TimeoutError("timeout")])
def test_measurement_exposes_network_failure_to_caller(monkeypatch, failure):
    monkeypatch.setattr(time_checker, "urlopen", Mock(side_effect=failure))
    with pytest.raises(type(failure)):
        TimeChecker(samples=1).measure_server_skew()
