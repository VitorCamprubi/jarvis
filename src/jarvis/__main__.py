"""Command-line entry point, used by `uv run jarvis` and `python -m jarvis`."""

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="Personal voice assistant.")
    options = parser.add_mutually_exclusive_group()
    options.add_argument(
        "--check",
        action="store_true",
        help="check the environment (Python, GPU, CUDA, audio, configuration) and exit",
    )
    options.add_argument(
        "--devices",
        action="store_true",
        help="list microphones and audio outputs, for audio.input_device/output_device",
    )
    options.add_argument(
        "--mic-test",
        action="store_true",
        help="measure background noise and your voice, and suggest vad.min_speech_level_dbfs",
    )
    args = parser.parse_args(argv)

    if args.check:
        from jarvis.doctor import run_checks

        return run_checks()
    if args.devices:
        from jarvis.doctor import print_devices

        return print_devices()
    if args.mic_test:
        from jarvis.doctor import mic_test

        return mic_test()

    from jarvis.app import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
