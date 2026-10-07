import argparse
import logging

from worker.runner import process_one, run_worker


def main() -> None:
    parser = argparse.ArgumentParser(description="VTEKI batch worker")
    parser.add_argument(
        "--once", action="store_true", help="Process at most one available job"
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.once:
        process_one()
    else:
        run_worker(args.poll_seconds)


if __name__ == "__main__":
    main()
