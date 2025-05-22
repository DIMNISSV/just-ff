# just_ff/exceptions.py

"""Exceptions specific to the just-ff library interactions."""


class FfmpegWrapperError(Exception):
    """Base exception for errors originating from the just-ff library."""
    pass


class FfmpegExecutableNotFoundError(FfmpegWrapperError, FileNotFoundError):
    """Raised when ffmpeg or ffprobe executable is not found."""

    def __init__(self, executable_name: str):
        self.executable_name = executable_name
        # f-строка для сообщения
        super().__init__(f"FFmpeg executable '{executable_name}' not found in PATH or configured path.")


class FfmpegProcessError(FfmpegWrapperError):
    """Raised when an ffmpeg/ffprobe process fails (non-zero exit code)."""

    def __init__(self, command: list[str], exit_code: int, stderr: str, stdout: str = ""):
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout
        # Ограничиваем stderr в сообщении для читаемости
        stderr_preview = stderr.strip()[-1000:] if stderr else "N/A"
        # f-строка для сообщения
        message = (
            f"FFmpeg process failed with exit code {exit_code}.\n"
            f"Command: {' '.join(command)}\n"
            f"Stderr (last 1000 chars):\n{stderr_preview}"
        )
        super().__init__(message)


class FfprobeJsonError(FfmpegWrapperError):
    """Raised when ffprobe output cannot be parsed as JSON."""

    def __init__(self, command: list[str], stdout: str, error: Exception):
        self.command = command
        self.stdout = stdout
        self.error = error
        stdout_preview = stdout.strip()[:500] if stdout else "N/A"
        # f-строка для сообщения
        message = (
            f"Failed to decode ffprobe JSON output.\n"
            f"Command: {' '.join(command)}\n"
            f"Error: {error}\n"
            f"Stdout (first 500 chars):\n{stdout_preview}"
        )
        super().__init__(message)


class CommandBuilderError(FfmpegWrapperError):
    """Raised for errors during FFmpeg command construction."""
    pass
