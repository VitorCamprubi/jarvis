"""Command-line entry point, used by `uv run jarvis` and `python -m jarvis`."""

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    if sys.stderr is None:  # started by pythonw (with Windows): there is no console at all
        sys.stdout = sys.stderr = Path(os.devnull).open("w", encoding="utf-8")  # noqa: SIM115
        from jarvis.windows.process import mark_windowless

        mark_windowless()  # errors then show in a message box

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
    options.add_argument(
        "--autostart",
        choices=["on", "off", "status"],
        help="start JARVIS with Windows, without a console window (or stop doing so)",
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
    if args.autostart:
        return autostart(args.autostart)

    from jarvis.app import run

    return run()


def autostart(action: str) -> int:
    from jarvis.windows import autostart

    if action == "on":
        print(f"JARVIS will start with Windows: {autostart.enable()}")
    elif action == "off":
        done = autostart.disable()
        print("JARVIS will no longer start with Windows." if done else "It was not set to.")
    else:
        command = autostart.current()
        print(f"Starts with Windows: {command}" if command else "Does not start with Windows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
