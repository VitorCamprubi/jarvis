"""Command-line entry point, used by `uv run jarvis` and `python -m jarvis`."""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="Personal voice assistant.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="check the environment (Python, GPU, configuration, secrets) and exit",
    )
    args = parser.parse_args(argv)

    if args.check:
        from jarvis.doctor import run_checks

        return run_checks()

    from jarvis.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
