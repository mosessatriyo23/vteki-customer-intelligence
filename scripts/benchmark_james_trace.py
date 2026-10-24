"""Manual read-only audit reconstruction latency smoke/benchmark.

Requires a running API and valid analyst/admin JWT supplied via environment.
A short localhost run is not proof of production SLA at representative load.
"""

import argparse
import json
import os
import statistics
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    args = parser.parse_args()
    jwt = os.getenv("VTEKI_TEST_JWT", "")
    if not jwt:
        parser.error("Set VTEKI_TEST_JWT in your shell (do not commit it)")
    if not (1 <= args.repetitions <= 100):
        parser.error("--repetitions must be from 1 to 100")
    if not args.correlation_id or len(args.correlation_id) > 128:
        parser.error("invalid --correlation-id length")
    endpoint = f"{args.url.rstrip('/')}/audit/decision-trace/{quote(args.correlation_id, safe='')}"
    elapsed = []
    try:
        for _ in range(args.repetitions):
            request = Request(endpoint, headers={"Authorization": f"Bearer {jwt}"})
            start = time.perf_counter()
            with urlopen(request, timeout=max(args.max_seconds + 10.0, 20.0)) as response:
                payload = json.load(response)
            elapsed.append(time.perf_counter() - start)
            if payload.get("correlation_id") != args.correlation_id:
                raise ValueError("Response correlation ID mismatch")
            if not payload.get("decision_steps") and not payload.get("audit_events"):
                raise ValueError("Empty trace: use a correlation ID with real events")
    except (HTTPError, URLError, TimeoutError, ValueError) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2
    slowest = max(elapsed)
    print(json.dumps({
        "samples": len(elapsed),
        "median_seconds": round(statistics.median(elapsed), 5),
        "max_seconds": round(slowest, 5),
        "target_seconds": args.max_seconds,
        "smoke_passed": slowest <= args.max_seconds,
    }, indent=2))
    return 0 if slowest <= args.max_seconds else 1


if __name__ == "__main__":
    raise SystemExit(main())
