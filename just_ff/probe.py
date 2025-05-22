# just_ff/probe.py

import json
import typing
import os

from just_ff.streams import MediaInfo, safe_float
from just_ff.process import run_command
from just_ff.exceptions import (
    FfmpegExecutableNotFoundError,
    FfmpegProcessError,
    FfprobeJsonError,
    FfmpegWrapperError
)


class FFprobeRunner:
    """Runs ffprobe commands to get media information."""

    DEFAULT_ARGS = ["-v", "quiet", "-print_format", "json"]

    def __init__(self, ffprobe_path: str = "ffprobe"):
        """
        Initializes the FFprobeRunner.

        Args:
            ffprobe_path: Path to the ffprobe executable. Defaults to 'ffprobe' (assumes in PATH).
        """
        self.ffprobe_path = ffprobe_path
        # self._verify_executable() # Опциональная проверка при инициализации

    def _verify_executable(self):
        """Checks if the configured ffprobe path is valid."""
        try:
            # Выполняем простую команду, чтобы проверить наличие
            run_command([self.ffprobe_path, "-version"], capture_output=False, check=True, timeout=5)
            print(f"FFprobe executable verified: {self.ffprobe_path}")
        except FileNotFoundError:
            raise FfmpegExecutableNotFoundError(self.ffprobe_path)
        except Exception as e:
            # Другие ошибки при запуске
            raise FfmpegWrapperError(f"Failed to verify ffprobe executable '{self.ffprobe_path}': {e}") from e

    def run_ffprobe(self, args: typing.List[str]) -> typing.Dict[str, typing.Any]:
        """
        Runs an ffprobe command with the given arguments and parses JSON output.

        Args:
            args: List of arguments to pass to ffprobe (excluding executable name and default args).

        Returns:
            Parsed JSON output as a dictionary.

        Raises:
            FfmpegExecutableNotFoundError: If ffprobe is not found.
            FfmpegProcessError: If ffprobe returns a non-zero exit code.
            FfprobeJsonError: If ffprobe output is not valid JSON.
            FfmpegWrapperError: For other unexpected errors.
        """
        # Убедимся, что -i аргумент, если он есть, находится в конце, как принято
        # Это важно для некоторых опций, которые должны идти после -i
        processed_args = args[:]  # Работаем с копией
        if "-i" in processed_args:
            i_index = processed_args.index("-i")
            # Перемещаем "-i" и следующий за ним аргумент (путь к файлу) в конец
            if i_index < len(processed_args) - 1:
                input_arg = processed_args.pop(i_index)
                input_path = processed_args.pop(i_index)  # Путь идет сразу после -i
                processed_args.extend([input_arg, input_path])
            else:
                print(f"Warning: '-i' found as the last argument in ffprobe args: {args}. May be incorrect.")

        command = [self.ffprobe_path] + self.DEFAULT_ARGS + processed_args
        # print(f"Running ffprobe: {' '.join(command)}") # run_command уже логирует

        try:
            # Используем run_command helper
            result = run_command(command, capture_output=True, check=True)
            # FFprobe JSON output is typically in stdout
            output_str = result.stdout

            if not output_str.strip():
                # Если вывод пустой, возможно, файл не существует или не поддерживается
                # run_command с check=True уже выбросил бы ошибку, если exit code != 0
                # Но если exit code 0 и вывод пустой, это тоже проблема.
                print(f"Warning: ffprobe returned empty output for command: {' '.join(command)}")
                # Вернем пустой словарь? Или выбросим ошибку? Выбросим ошибку парсинга.
                raise FfprobeJsonError(command, "", ValueError("Empty output"))

            try:
                # Парсим JSON
                return json.loads(output_str)
            except json.JSONDecodeError as json_e:
                # Оборачиваем ошибку парсинга
                raise FfprobeJsonError(command, output_str, json_e)

        except FfmpegProcessError as proc_e:
            # FfmpegProcessError уже содержит всю информацию
            raise proc_e
        except FfmpegWrapperError as e:
            # Ошибки вроде FileNotFoundError уже обернуты в run_command
            raise e
        except Exception as e:
            # Оборачиваем любую другую неожиданную ошибку
            raise FfmpegWrapperError(f"Unexpected error running ffprobe: {e}") from e

    def get_media_info(self, file_path: str) -> MediaInfo:
        """
        Gets comprehensive format and stream information for a media file.

        Args:
            file_path: Path to the media file.

        Returns:
            A MediaInfo dataclass instance containing parsed information.

        Raises:
            FileNotFoundError: If the input file_path does not exist.
            FfmpegWrapperError (and subtypes): If ffprobe execution or parsing fails.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file not found: {file_path}")

        args = ["-show_format", "-show_streams", "-i", file_path]
        ffprobe_output = self.run_ffprobe(args)

        # Парсим вывод в MediaInfo
        try:
            # from_ffprobe_dict уже обрабатывает структуру
            media_info = MediaInfo.from_ffprobe_dict(ffprobe_output)
            # Note: stream.unique_id is NOT set here. It's done in JustConverter.
            # MediaInfo.stream_id_map will be empty until update_stream_id_map is called externally.
            return media_info
        except Exception as e:
            # Оборачиваем ошибки при парсинге в датаклассы
            raise FfmpegWrapperError(f"Error parsing ffprobe output into MediaInfo: {e}") from e

    def get_duration(self, file_path: str) -> typing.Optional[float]:
        """
        Gets the duration of a media file in seconds.
        Tries format duration first, then the first video stream duration.

        Args:
            file_path: Path to the media file.

        Returns:
            Duration in seconds as a float, or None if undetermined or invalid.

        Raises:
            FileNotFoundError: If the input file_path does not exist.
            FfmpegWrapperError (and subtypes): If ffprobe execution fails for a critical step.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file not found: {file_path}")

        duration: typing.Optional[float] = None

        # 1. Try Format Duration
        format_args = ["-show_entries", "format=duration", "-i", file_path]
        try:
            format_output = self.run_ffprobe(format_args)
            duration_str = format_output.get("format", {}).get("duration")
            duration = safe_float(duration_str)  # Use safe conversion
            if duration is not None and duration <= 0: duration = None  # Игнорируем 0 или отрицательное

        except FfprobeJsonError as e:
            print(f"Warning: ffprobe format duration JSON error for '{file_path}': {e.error}")
        except FfmpegProcessError as e:
            # Логируем ошибку, но не выбрасываем, т.к. будем пробовать стрим
            print(
                f"Warning: ffprobe failed getting format duration for '{file_path}' (Stderr: {e.stderr.strip()[:200]}...)")
        except FfmpegWrapperError as e:
            # Если это ошибка вроде executable not found, выбрасываем ее
            raise e
        except Exception as e:
            # Другие ошибки при запуске run_ffprobe
            print(f"Warning: Unexpected error getting format duration for '{file_path}': {e}")

        # 2. Try First Video Stream Duration (if format duration failed or was invalid)
        if duration is None:
            stream_args = ["-select_streams", "v:0", "-show_entries", "stream=duration", "-i", file_path]
            try:
                stream_output = self.run_ffprobe(stream_args)
                streams = stream_output.get("streams", [])
                if streams:
                    duration_str = streams[0].get("duration")
                    stream_duration = safe_float(duration_str)
                    if stream_duration is not None and stream_duration > 0:
                        duration = stream_duration  # Используем положительную длительность стрима

            except FfprobeJsonError as e:
                print(f"Warning: ffprobe stream duration JSON error for '{file_path}': {e.error}")
            except FfmpegProcessError:
                # Игнорируем ошибки здесь (например, у файла нет видео потока)
                pass
            except FfmpegWrapperError as e:
                # Если это ошибка вроде executable not found, выбрасываем ее
                raise e
            except Exception as e:
                print(f"Warning: Unexpected error getting stream duration for '{file_path}': {e}")

        # Возвращаем длительность только если она определена и положительна
        return duration if duration is not None and duration > 0 else None

    # TODO: Add caching for ffprobe results
