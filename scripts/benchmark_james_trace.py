"""End-to-end audit trace latency and completeness benchmark."""

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
    parser.add_argument("--limit", type=int, default=5000)
    args = parser.parse_args()

    jwt = os.getenv("VTEKI_TEST_JWT", "")
    if not jwt:
        parser.error("Set VTEKI_TEST_JWT in your shell")

    if not 1 <= args.repetitions <= 100:
        parser.error("--repetitions must be from 1 to 100")

    if not 1 <= args.limit <= 5000:
        parser.error("--limit must be from 1 to 5000")

    if not args.correlation_id or len(args.correlation_id) > 128:
        parser.error("Invalid correlation ID")

    endpoint = (
        f"{args.url.rstrip('/')}/audit/decision-trace/"
        f"{quote(args.correlation_id, safe='')}?limit={args.limit}"
    )

    elapsed = []
    final_counts = {}

    try:
        for sample in range(args.repetitions):
            request = Request(
                endpoint,
                headers={"Authorization": f"Bearer {jwt}"},
            )

            start = time.perf_counter()

            with urlopen(
                request,
                timeout=max(args.max_seconds + 10.0, 20.0),
            ) as response:
                payload = json.load(response)

            elapsed.append(time.perf_counter() - start)

            if not isinstance(payload, dict):
                raise ValueError("Invalid response format")

            if payload.get("correlation_id") != args.correlation_id:
                raise ValueError("Correlation ID mismatch")

            required_fields = (
                "decision_steps",
                "audit_events",
                "decision_steps_returned",
                "audit_events_returned",
                "decision_steps_truncated",
                "audit_events_truncated",
            )

            missing = [field for field in required_fields if field not in payload]
            if missing:
                raise ValueError(f"Missing response fields: {missing}")

            decisions = payload["decision_steps"]
            events = payload["audit_events"]

            if not isinstance(decisions, list) or not isinstance(events, list):
                raise ValueError("Trace data must be returned as lists")

            if payload["decision_steps_returned"] != len(decisions):
                raise ValueError("Decision trace count mismatch")

            if payload["audit_events_returned"] != len(events):
                raise ValueError("Audit event count mismatch")

            if payload["decision_steps_truncated"] is not False:
                raise ValueError("Decision trace is truncated")

            if payload["audit_events_truncated"] is not False:
                raise ValueError("Audit events are truncated")

            if not decisions and not events:
                raise ValueError("Empty trace: use a correlation ID with real events")

            final_counts = {
                "decision_steps": len(decisions),
                "audit_events": len(events),
            }

            print(
                f"Sample {sample + 1}: {elapsed[-1]:.5f}s, "
                f"decisions={len(decisions)}, "
                f"audit_events={len(events)}"
            )

    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        KeyError,
        TypeError,
    ) as error:
        print(f"FAILED: {error}", file=sys.stderr)
        return 2

    slowest = max(elapsed)
    passed = slowest <= args.max_seconds

    print(
        json.dumps(
            {
                "samples": len(elapsed),
                "median_seconds": round(statistics.median(elapsed), 5),
                "max_seconds": round(slowest, 5),
                "target_seconds": args.max_seconds,
                "result_counts": final_counts,
                "truncation_detected": False,
                "completeness_verified": True,
                "sla_passed": passed,
            },
            indent=2,
        )
    )

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
