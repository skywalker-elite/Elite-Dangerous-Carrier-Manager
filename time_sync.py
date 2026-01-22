import time
from datetime import datetime, UTC
import json
from urllib.request import urlopen, Request

class ServerClock:
    """
    Application-level clock synced to a server unixTimestamp endpoint.
    - Does NOT change system time.
    - Uses monotonic time to advance smoothly after sync.
    """
    def __init__(self, url: str, timeout: float = 2.0):
        self.url = url
        self.timeout = timeout

        self._server_ts_at_sync: float | None = None
        self._mono_at_sync: float | None = None
        self._rtt_last: float | None = None

    def sync(self) -> float:
        """
        Syncs to server time. Returns estimated offset vs local wall clock (seconds),
        mainly for diagnostics; internal clock uses monotonic advancement.
        """
        t0 = time.monotonic()

        req = Request(self.url)
        with urlopen(req, timeout=self.timeout) as resp:
            body = resp.read()

        t1 = time.monotonic()
        self._rtt_last = t1 - t0
        t_mid = (t0 + t1) / 2.0

        # Parse <unixTimestamp>1768269699</unixTimestamp>
        print(body)
        # Parse the byte string into a dictionary
        data_dict = json.loads(body)

        # Access the number
        timestamp = data_dict['unixTimestamp']

        server_ts = float(timestamp)  # assume seconds
        self._server_ts_at_sync = server_ts
        self._mono_at_sync = t_mid

        # Diagnostic offset vs local wall clock (not used for progression)
        return server_ts - time.time()

    def now(self) -> float:
        """
        Returns current estimated server epoch seconds (UTC).
        """
        if self._server_ts_at_sync is None or self._mono_at_sync is None:
            raise RuntimeError("Clock is not synced yet. Call sync().")

        return self._server_ts_at_sync + (time.monotonic() - self._mono_at_sync)

    @property
    def rtt_last(self) -> float | None:
        return self._rtt_last


# ---- Usage example ----
if __name__ == "__main__":
    clock = ServerClock("https://api.orerve.net/2.0/server/time")
    offset = clock.sync()
    print(f"Initial offset vs local wall clock: {offset:+.3f}s (RTT={clock.rtt_last:.3f}s)")
    
    for _ in range(5):
        now = clock.now()
        print(f"Server time now: {datetime.fromtimestamp(now, UTC)} UTC)")
        time.sleep(1)
