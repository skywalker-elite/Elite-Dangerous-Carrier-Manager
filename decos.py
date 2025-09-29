import time
import threading
import functools
from collections import deque

def rate_limited(max_calls: int, period: float):
    """
    Decorator that allows up to max_calls per period (seconds),
    caching and returning the last result in between bursts,
    separately for each distinct (args, kwargs) combination.
    """
    state: dict = {}  # maps (args, sorted(kwargs)) -> {'times': deque, 'cache': result}

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            # build a hashable key for this call
            key = (args, tuple(sorted(kwargs.items())))
            if key not in state:
                state[key] = {'times': deque(), 'cache': None}

            record = state[key]
            times: deque[float] = record['times']

            # drop timestamps older than our window
            while times and now - times[0] > period:
                times.popleft()

            # if under limit, perform real call and update cache
            if len(times) < max_calls:
                times.append(now)
                try:
                    record['cache'] = func(*args, **kwargs)
                except Exception:
                    # on failure, keep last cache
                    pass

            return record['cache']
        return wrapper
    return decorator

def debounce(wait_seconds):
    """
    Postpone a function’s execution until wait_seconds have elapsed since
    the last call.  If the first arg has a .root, use root.after/after_cancel
    so the callback won’t fire after the window is closed.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            self = args[0] if args else None
            root = getattr(self, 'root', None)
            # use a unique attr per instance+method:
            after_attr = f'__debounce_after_id_{fn.__name__}'
            if root and hasattr(root, 'after'):
                # cancel previous
                prev = getattr(self, after_attr, None)
                if prev:
                    try:
                        root.after_cancel(prev)
                    except Exception:
                        pass
                # schedule new
                handle = root.after(int(wait_seconds * 1000), lambda: fn(*args, **kwargs))
                setattr(self, after_attr, handle)
            else:
                # fallback to threading.Timer
                timer_attr = f'__debounce_timer_{fn.__name__}'
                prev_timer = getattr(self, timer_attr, None)
                if prev_timer:
                    prev_timer.cancel()
                t = threading.Timer(wait_seconds, lambda: fn(*args, **kwargs))
                setattr(self, timer_attr, t)
                t.start()
        return wrapped
    return decorator