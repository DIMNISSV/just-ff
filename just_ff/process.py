# just_ff/process.py
import shlex
import subprocess
import typing
import os
import re
import time
import threading

from just_ff.exceptions import FfmpegExecutableNotFoundError, FfmpegProcessError, FfmpegWrapperError


# --- Basic Command Runner ---

def run_command(
        command: typing.List[str],
        capture_output: bool = True,
        check: bool = True,
        timeout: typing.Optional[float] = None,
        **kwargs  # Pass additional args to subprocess.run
) -> subprocess.CompletedProcess:
    """
    Runs an external command using subprocess.run.

    Args:
        command: List of command arguments.
        capture_output: If True, capture stdout and stderr.
        check: If True, raise CalledProcessError on non-zero exit code.
        timeout: Optional timeout in seconds.
        **kwargs: Additional arguments for subprocess.run.

    Returns:
        subprocess.CompletedProcess instance.

    Raises:
        FfmpegExecutableNotFoundError: If the command executable is not found.
        subprocess.CalledProcessError: If check is True and command fails.
        subprocess.TimeoutExpired: If timeout is reached.
        FfmpegWrapperError: For other unexpected errors.
    """
    executable = command[0]
    # Убедимся, что все аргументы - строки
    command_str_list = [str(arg) for arg in command]
    print(f"Running command: {' '.join(shlex.quote(arg) for arg in command_str_list)}")  # Логируем команду с цитатами

    # Hide console window on Windows
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    try:
        # Используем command_str_list для выполнения
        process = subprocess.run(
            command_str_list,
            capture_output=capture_output,
            check=check,
            text=True,  # Декодируем вывод как текст
            encoding='utf-8',
            errors='replace',  # Обработка ошибок декодирования
            timeout=timeout,
            startupinfo=startupinfo,
            **kwargs
        )
        # Возвращаем результат как есть
        return process
    except FileNotFoundError as e:
        raise FfmpegExecutableNotFoundError(executable) from e
    except subprocess.CalledProcessError as e:
        # Перехватываем и оборачиваем стандартную ошибку subprocess
        raise FfmpegProcessError(
            command=e.cmd,
            exit_code=e.returncode,
            stderr=e.stderr or "",
            stdout=e.stdout or ""
        ) from e
    except subprocess.TimeoutExpired as e:
        print(f"Command '{executable}' timed out after {timeout} seconds.")
        # Если процесс был запущен с capture_output=True, его stdout/stderr доступны в e.stdout/e.stderr
        raise FfmpegWrapperError(
            f"Command timed out: {e}"
        ) from e  # Оборачиваем для консистентности
    except Exception as e:
        print(f"An unexpected error occurred running command '{executable}': {e}")
        # Оборачиваем любую другую ошибку
        raise FfmpegWrapperError(f"Unexpected error running {executable}: {e}") from e


# --- FFmpeg Runner with Progress ---

# Regex to capture progress information from ffmpeg stderr
# Captures frame, fps, q, size, time, bitrate, speed
PROGRESS_RE = re.compile(
    r"frame=\s*(?P<frame>\d+)\s+"
    r"fps=\s*(?P<fps>[\d.]+)\s+"
    r"q=\s*(?P<q>[\d.-]+)\s+"
    r"(?:L?size=\s*(?P<size>\d+)\w*\s+)?"  # Optional size (Lsize)
    r"time=\s*(?P<time>[\d:.]+)\s+"
    r"bitrate=\s*(?P<bitrate>[\d.]+)\w*/s\s+"
    r"speed=\s*(?P<speed>[\d.]+)x"
)


def _parse_time_to_seconds(time_str: str) -> typing.Optional[float]:
    """Parses HH:MM:SS.ms string to seconds."""
    parts = time_str.split(':')
    try:
        if len(parts) == 3:
            h, m, s = map(float, parts)
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:  # MM:SS.ms ?
            m, s = map(float, parts)
            return m * 60 + s
        elif len(parts) == 1:  # Seconds only?
            return float(parts[0])
    except ValueError:
        pass
    return None


def run_ffmpeg_with_progress(
        command: typing.List[str],
        duration_sec: typing.Optional[float],  # Total duration for percentage calculation
        progress_callback: typing.Optional[typing.Callable[[float], None]] = None,  # Callback(percentage)
        process_callback: typing.Optional[typing.Callable[[subprocess.Popen], None]] = None,  # Callback(process)
        check: bool = True  # Raise error on non-zero exit?
) -> bool:
    """
    Runs an FFmpeg command using Popen, capturing stderr line-by-line
    to parse progress and invoke callbacks.

    Args:
        command: List of command arguments for ffmpeg.
        duration_sec: Total expected duration in seconds (from ffprobe).
                      Required for percentage calculation if progress_callback is used.
        progress_callback: Optional function called with progress percentage (0.0-100.0).
        process_callback: Optional function called with the Popen process object,
                          allowing the caller to store it (e.g., for cancellation).
        check: If True, raise FfmpegProcessError on non-zero exit code.

    Returns:
        True if the command completed successfully (exit code 0), False otherwise.

    Raises:
        FfmpegExecutableNotFoundError: If ffmpeg is not found.
        FfmpegProcessError: If check is True and the process fails.
        TypeError: If duration_sec is None but progress_callback is provided.
        FfmpegWrapperError: For other unexpected errors.
    """
    executable = command[0]
    command_str_list = [str(arg) for arg in command]  # Убедимся, что все - строки

    if progress_callback and (duration_sec is None or duration_sec <= 0):
        # Валидация длительности только если нужен прогресс
        raise TypeError("duration_sec must be a positive number when using progress_callback")

    print(f"Running FFmpeg with progress: {' '.join(shlex.quote(arg) for arg in command_str_list)}")

    # Hide console window on Windows
    startupinfo = None
    # creationflags = 0 # Оставляем закомментированным
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        # creationflags = subprocess.CREATE_NO_WINDOW # Используем осторожно

    # Используем список строк для stderr для эффективного сбора
    stderr_lines: typing.List[str] = []
    last_progress_pct = -1.0

    try:
        process = subprocess.Popen(
            command_str_list,  # Используем список строк
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            startupinfo=startupinfo,
            # creationflags=creationflags,
            # bufsize=1 # Может помочь с построчным выводом, но может иметь побочки
        )

        # Отправить объект процесса обратно
        if process_callback:
            process_callback(process)

        # Читаем stderr в отдельном потоке, чтобы не блокировать основной поток при больших объемах вывода
        # или если stdout тоже используется.
        # Для простых случаев с FFmpeg (лог только в stderr) можно читать прямо.
        # Для надежности: читаем в потоке.
        def read_stderr(pipe, output_list):
            try:
                # Читаем построчно
                for line in pipe:
                    output_list.append(line)
                    # Обработка прогресса прямо здесь (или в основном потоке?)
                    # Обработка в основном потоке через Signal/Slot (если в Qt) или Queue (если в чистом Python)
                    # Для этой функции просто добавляем в список. Парсинг в основном потоке.
            except Exception as e:
                print(f"Error reading stderr in thread: {e}")
            finally:
                pipe.close()

        # Запускаем поток для чтения stderr
        stderr_thread = threading.Thread(target=read_stderr, args=(process.stderr, stderr_lines),
                                         daemon=True)  # Daemon=True, чтобы поток завершился с основным
        stderr_thread.start()

        # В основном потоке ждем завершения процесса ИЛИ отмены
        # Popen.poll() возвращает код завершения или None
        while stderr_thread.is_alive() or process.poll() is None:
            # Проверяем, появились ли новые строки
            if stderr_lines:
                # Обрабатываем строки. Очищаем список после обработки.
                processed_lines = list(stderr_lines)
                stderr_lines.clear()  # Очищаем для следующих строк

                for line in processed_lines:
                    line = line.strip()
                    match = PROGRESS_RE.search(line)
                    if match and progress_callback and duration_sec and duration_sec > 0:
                        progress_data = match.groupdict()
                        current_time_str = progress_data.get("time")
                        if current_time_str:
                            current_sec = _parse_time_to_seconds(current_time_str)
                            if current_sec is not None:
                                percentage = min(100.0, max(0.0, (current_sec / duration_sec) * 100.0))
                                # Отправляем прогресс, если изменился достаточно
                                if percentage >= last_progress_pct + 0.1 or percentage == 100.0:  # Меньший порог для плавности
                                    try:
                                        progress_callback(percentage)
                                    except Exception as cb_err:
                                        print(f"Warning: Progress callback failed: {cb_err}")
                                    last_progress_pct = percentage
                    elif line and not line.startswith(("frame=", "size=", "time=", "bitrate=", "speed=",
                                                       "Parsed_")):  # Игнорируем Parsed_ filter info
                        # Печатаем не-прогресс строки в консоль (предупреждения, ошибки)
                        # В GUI их нужно передавать через отдельный лог-колбэк
                        print(f"  ffmpeg: {line}")

            # Небольшая пауза, чтобы не грузить CPU в цикле
            time.sleep(0.01)

        # Ждем завершения потока чтения stderr
        stderr_thread.join()

        # Ждем завершения процесса, если он еще не завершился
        exit_code = process.wait()

        # Если были какие-то строки, которые могли остаться в буфере после выхода из цикла while/join
        if stderr_lines:
            for line in stderr_lines:
                line = line.strip()
                # Финальная попытка парсинга или печати
                match = PROGRESS_RE.search(line)  # Парсинг последних строк
                if match and progress_callback and duration_sec and duration_sec > 0:
                    progress_data = match.groupdict()
                    current_time_str = progress_data.get("time")
                    if current_time_str:
                        current_sec = _parse_time_to_seconds(current_time_str)
                        if current_sec is not None:
                            percentage = min(100.0, max(0.0, (current_sec / duration_sec) * 100.0))
                            if percentage > last_progress_pct:  # Убедимся, что финальный 100% всегда отправлен
                                try:
                                    progress_callback(percentage)
                                except:
                                    pass
                                last_progress_pct = percentage
                elif line and not line.startswith(("frame=", "size=", "time=", "bitrate=", "speed=", "Parsed_")):
                    print(f"  ffmpeg: {line}")

        # Собираем полный stderr из списка строк
        full_stderr = "".join(stderr_lines)  # Теперь все строки собраны

        if exit_code != 0:
            # Оборачиваем ошибку процесса
            raise FfmpegProcessError(
                command=command,
                exit_code=exit_code,
                stderr=full_stderr,  # Передаем собранный stderr
                stdout=process.stdout.read()  # Читаем stdout
            )
        else:
            return True

    except FileNotFoundError as e:
        raise FfmpegExecutableNotFoundError(executable) from e
    except FfmpegProcessError as e:  # Если ошибка уже обернута
        raise e
    except Exception as e:
        # Оборачиваем любую другую неожиданную ошибку
        raise FfmpegWrapperError(f"Unexpected error during FFmpeg execution: {e}") from e
