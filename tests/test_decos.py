"""Deterministic scheduling tests; no real timers or sleeping."""
from types import SimpleNamespace

import pytest

import decos


def test_rate_limit_caches_per_arguments_and_resets_after_window(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(decos, "time", SimpleNamespace(time=lambda: clock[0]))
    calls = []

    @decos.rate_limited(max_calls=2, period=10)
    def compute(value, scale=1):
        calls.append((value, scale))
        return value * scale + len(calls)

    assert compute(10, scale=2) == 21
    assert compute(10, scale=2) == 22
    assert compute(10, scale=2) == 22
    assert compute(20, scale=2) == 43
    clock[0] = 110.001
    assert compute(10, scale=2) == 24
    assert len(calls) == 4


def test_rate_limit_rethrows_failure_until_next_window_then_recovers(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(decos, "time", SimpleNamespace(time=lambda: clock[0]))
    calls = []

    @decos.rate_limited(max_calls=1, period=10)
    def compute():
        calls.append(True)
        if len(calls) == 1:
            raise ValueError("synthetic transient failure")
        return 42

    for _ in range(2):
        with pytest.raises(ValueError):
            compute()
    assert len(calls) == 1
    clock[0] = 111
    assert compute() == 42
    assert len(calls) == 2


class Scheduler:
    def __init__(self):
        self.pending = {}
        self.sequence = 0
        self.delays = []

    def after(self, milliseconds, callback):
        self.sequence += 1
        self.delays.append(milliseconds)
        self.pending[self.sequence] = callback
        return self.sequence

    def after_cancel(self, handle):
        self.pending.pop(handle)

    def run(self):
        callbacks = list(self.pending.values())
        self.pending.clear()
        for callback in callbacks:
            callback()


def test_debounce_coalesces_latest_arguments_per_instance_and_method():
    class Consumer:
        def __init__(self):
            self.root = Scheduler()
            self.results = []

        @decos.debounce(0.25)
        def update(self, value):
            self.results.append(value)

        @decos.debounce(0.25)
        def refresh(self, value):
            self.results.append(value)

    first, second = Consumer(), Consumer()
    first.update("obsolete")
    first.update("latest")
    first.refresh("separate-method")
    second.update("separate-instance")
    assert first.results == []
    assert len(first.root.pending) == 2
    first.root.run()
    second.root.run()
    assert first.results == ["latest", "separate-method"]
    assert second.results == ["separate-instance"]
    assert set(first.root.delays) == {250}


def test_debounce_thread_fallback_cancels_obsolete_timer(monkeypatch):
    timers = []

    class Timer:
        def __init__(self, delay, callback):
            self.delay, self.callback, self.cancelled, self.started = delay, callback, False, False
            timers.append(self)

        def cancel(self):
            self.cancelled = True

        def start(self):
            self.started = True

    monkeypatch.setattr(decos, "threading", SimpleNamespace(Timer=Timer))

    class Consumer:
        @decos.debounce(0.5)
        def update(self, value):
            self.value = value

    consumer = Consumer()
    consumer.update(1)
    consumer.update(2)
    assert timers[0].cancelled
    assert timers[1].started and not timers[1].cancelled
    assert timers[1].delay == 0.5
    timers[1].callback()
    assert consumer.value == 2
