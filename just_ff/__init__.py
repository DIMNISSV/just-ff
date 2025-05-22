# just_ff/__init__.py
"""
just-ff: A Python wrapper for FFmpeg and FFprobe.

Provides tools for media analysis and command building.
"""

from .exceptions import (
    FfmpegWrapperError,
    FfmpegExecutableNotFoundError,
    FfmpegProcessError,
    FfprobeJsonError,
    CommandBuilderError
)
from .streams import MediaInfo, StreamInfo, FormatInfo, safe_float, safe_int
from .process import run_command, run_ffmpeg_with_progress
from .probe import FFprobeRunner
from .command import FFmpegCommandBuilder

__all__ = [
    "FfmpegWrapperError",
    "FfmpegExecutableNotFoundError",
    "FfmpegProcessError",
    "FfprobeJsonError",
    "CommandBuilderError",
    "MediaInfo",
    "StreamInfo",
    "FormatInfo",
    "safe_float",
    "safe_int",
    "run_command",
    "run_ffmpeg_with_progress",
    "FFprobeRunner",
    "FFmpegCommandBuilder",
]

# --- Информация о версии пакета ---
# Poetry управляет версией в pyproject.toml
# Можно читать версию оттуда, но это усложняет __init__
# Проще установить версию здесь вручную или использовать пакеты типа importlib.metadata (Python 3.8+)
# try:
#     from importlib.metadata import version, PackageNotFoundError
# except ImportError:
#     # Fallback for Python < 3.8
#     try:
#         from importlib_metadata import version, PackageNotFoundError
#     except ImportError:
#         raise ImportError("Requires importlib-metadata for Python < 3.8")
# try:
#     __version__ = version("just-ff")
# except PackageNotFoundError:
#     # package is not installed
#     __version__ = "unknown"
#
# # Добавим версию в __all__
# __all__.append("__version__")

# Для простоты пока установим версию вручную
__version__ = "0.1.3-beta"
__all__.append("__version__")
