"""Make the CUDA libraries from NVIDIA's pip wheels loadable on Windows (ADR-014).

nvidia-cublas-cu12 and nvidia-cudnn-cu12 install their DLLs under site-packages/nvidia/*/bin,
which Windows does not search. CTranslate2 loads them lazily, on the first GPU inference.
"""

import importlib.util
import os
import sys
from pathlib import Path

REQUIRED_DLLS = ("cublas64_12.dll", "cudnn64_9.dll")

# Keep the handles: closing one would remove its directory from the search path.
_registered: list[object] = []


def nvidia_dll_dirs() -> list[Path]:
    spec = importlib.util.find_spec("nvidia")
    if spec is None or spec.submodule_search_locations is None:
        return []
    return sorted(
        bin_dir
        for root in spec.submodule_search_locations
        for bin_dir in Path(root).glob("*/bin")
        if bin_dir.is_dir()
    )


def register_nvidia_dlls() -> list[Path]:
    """Add the wheels' DLL folders to the DLL search path; returns the folders added."""
    if sys.platform != "win32":
        return []
    dirs = nvidia_dll_dirs()
    for bin_dir in dirs:
        _registered.append(os.add_dll_directory(str(bin_dir)))
        # Some loaders only honour PATH, so prepend there as well.
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    return dirs


def missing_dlls(dirs: list[Path]) -> list[str]:
    return [dll for dll in REQUIRED_DLLS if not any((d / dll).exists() for d in dirs)]
