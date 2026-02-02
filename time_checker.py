import time
import json
from urllib.request import Request, urlopen

class TimeChecker():
    def __init__(self, url: str = "https://api.orerve.net/2.0/server/time", samples: int = 3, spacing_s: float = 1.1, timeout: float = 2.0, threshold_s: float = 1.5, margin_s: float = 0.5):
        self.url = url
        self.samples = samples
        self.spacing_s = spacing_s
        self.timeout = timeout
        self.threshold_s = threshold_s
        self.margin_s = margin_s
    def measure_server_skew(self) -> dict:
        """
        Returns a dict with:
        - diff_s: estimated (server - local) seconds (positive means server ahead)
        - rtt_s: RTT of chosen sample
        - uncertainty_s: ~0.5s quantization + RTT/2
        - all: list of per-sample measurements
        Chooses the sample with the smallest RTT.
        """
    
        results = []

        for i in range(self.samples):
            t0m = time.monotonic()
            t0w = time.time()

            req = Request(self.url)
            with urlopen(req, timeout=self.timeout) as resp:
                body = resp.read()

            t1m = time.monotonic()
            t1w = time.time()

            rtt = t1m - t0m
            w_mid = (t0w + t1w) / 2.0

            data_dict = json.loads(body)
            timestamp = data_dict['unixTimestamp']
            server_ts_int = int(timestamp)
            # Center the integer second (assumes server_ts_int is floor/whole-second time)
            server_ts = server_ts_int + 0.5

            diff = server_ts - w_mid
            uncertainty = 0.5 + (rtt / 2.0)

            results.append({
                "server_ts_int": server_ts_int,
                "diff_s": diff,
                "rtt_s": rtt,
                "uncertainty_s": uncertainty,
            })

            if i < self.samples - 1:
                time.sleep(self.spacing_s)

        best = min(results, key=lambda x: x["rtt_s"])
        return {
            "diff_s": best["diff_s"],
            "rtt_s": best["rtt_s"],
            "uncertainty_s": best["uncertainty_s"],
            "all": results,
        }

    def should_warn(self, diff_s: float, uncertainty_s: float) -> bool:
        # Warn only if discrepancy is clearly beyond measurement noise and a user-facing threshold
        return abs(diff_s) > max(self.threshold_s, uncertainty_s + self.margin_s)
    
    def check_and_warn(self) -> tuple[bool, str]:
        """
        Measures server skew and returns (should_warn, warning_message)
        """
        m = self.measure_server_skew()
        warn = self.should_warn(m["diff_s"], m["uncertainty_s"])
        message = ""
        if warn:
            direction = "ahead of" if m["diff_s"] > 0 else "behind"
            message = (f"WARNING: Your clock is ~{abs(m['diff_s']):.1f}s {direction} the game server "
                       f"(RTT={m['rtt_s']*1000:.0f}ms, uncertainty≈±{m['uncertainty_s']:.2f}s).")
        else:
            message = (f"OK: diff={m['diff_s']:+.2f}s (RTT={m['rtt_s']*1000:.0f}ms, uncertainty≈±{m['uncertainty_s']:.2f}s)")
        return (warn, message)

# Example
if __name__ == "__main__":
    checker = TimeChecker()
    warn, message = checker.check_and_warn()

    print(message)

