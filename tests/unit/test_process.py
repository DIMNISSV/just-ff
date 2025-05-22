# tests/unit/test_process.py
import pytest
import subprocess
import os
import time

# --- Импорты из тестируемой библиотеки ---
from just_ff.process import run_command, run_ffmpeg_with_progress
from just_ff.exceptions import (
    FfmpegWrapperError,
    FfmpegExecutableNotFoundError,
    FfmpegProcessError,
    FfprobeJsonError,
)


# --- Конец импортов ---

# Фикстуры ffmpeg_path, ffprobe_path, tmp_output_dir определены в conftest.py


def test_run_command_success(ffmpeg_path):
    # Тестируем успешное выполнение простой команды
    command = [ffmpeg_path, "-version"]
    result = run_command(command, check=True)

    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 0
    assert result.stdout is not None  # stdout должен быть захвачен
    assert "ffmpeg version" in result.stdout.lower()  # Проверяем часть вывода
    assert result.stderr is not None  # stderr тоже захвачен (там может быть билд инфо)


def test_run_command_not_found():
    # Тестируем ошибку FileNotFoundError
    command = ["non_existent_ffmpeg", "-version"]
    with pytest.raises(FfmpegExecutableNotFoundError) as excinfo:
        run_command(command)

    assert "non_existent_ffmpeg" in str(excinfo.value)
    assert isinstance(excinfo.value, FileNotFoundError)  # Проверяем наследование


def test_run_command_failure(ffmpeg_path):
    # Тестируем ошибку выполнения (некорректные аргументы)
    # Использование невалидного кодека должно вызвать ошибку
    command = [ffmpeg_path, "-f", "lavfi", "-i", "color=c=red", "-frames:v", "1", "-c:v", "invalid_codec", "output.mp4"]
    # Запускаем без check=True сначала, чтобы увидеть returncode
    result_no_check = run_command(command, check=False, capture_output=True)
    assert result_no_check.returncode != 0  # Должен быть ненулевой код

    # Теперь запускаем с check=True, ожидаем исключение
    command_with_check = [ffmpeg_path, "-f", "lavfi", "-i", "color=c=red", "-frames:v", "1", "-c:v", "invalid_codec",
                          "output.mp4"]
    with pytest.raises(FfmpegProcessError) as excinfo:
        run_command(command_with_check, check=True, capture_output=True)

    assert excinfo.value.exit_code != 0
    assert "invalid_codec" in excinfo.value.stderr  # Проверяем наличие ошибки в stderr
    assert excinfo.value.command == command_with_check  # Проверяем, что команда сохранена
    assert isinstance(excinfo.value, FfmpegWrapperError)  # Проверяем наследование


def test_run_ffmpeg_with_progress_success(ffmpeg_path, tmp_output_dir):
    # Тестируем успешное выполнение с прогрессом
    # Конвертация короткого файла с известной длительностью
    input_file = "color=c=red:s=320x240:d=5"  # lavfi source
    output_file = os.path.join(tmp_output_dir, "output_progress.mp4")
    duration_sec = 5.0  # Из lavfi source

    command = [ffmpeg_path, "-f", "lavfi", "-i", input_file, "-frames:v", "125",  # 5 sec * 25 fps
               "-c:v", "libx264", "-preset", "ultrafast", "-f", "mp4", output_file]  # Указываем формат явно

    progress_values = []
    process_obj = None

    def progress_callback(percentage):
        progress_values.append(percentage)
        # print(f"-> Progress: {percentage:.1f}%") # Отладка

    def process_callback(process):
        nonlocal process_obj  # Чтобы изменить переменную из внешней области
        process_obj = process

    result = run_ffmpeg_with_progress(
        command,
        duration_sec=duration_sec,
        progress_callback=progress_callback,
        process_callback=process_callback,
        check=True  # Ожидаем успех
    )

    assert result is True  # Должно вернуть True при успехе
    assert process_obj is not None  # Должен быть передан объект процесса

    # Проверяем, что прогресс обновлялся
    assert len(progress_values) > 0  # Должно быть хотя бы несколько значений (100%)
    assert progress_values[0] >= 0.0  # Прогресс начинается с 0 или близко
    assert progress_values[-1] == 100.0  # Прогресс заканчивается 100%

    assert os.path.exists(output_file)  # Проверяем, что файл создан


def test_run_ffmpeg_with_progress_failure(ffmpeg_path, tmp_output_dir):
    # Тестируем ошибку выполнения с прогрессом
    input_file = "color=c=red:s=320x240:d=1"
    output_file = os.path.join(tmp_output_dir, "output_fail.mp4")
    duration_sec = 1.0
    # Некорректный кодек для вывода
    command = [ffmpeg_path, "-f", "lavfi", "-i", input_file, "-c:v", "invalid_codec_for_progress", output_file]

    progress_values = []
    process_obj = None

    def progress_callback(percentage):
        progress_values.append(percentage)

    def process_callback(process):
        nonlocal process_obj
        process_obj = process

    with pytest.raises(FfmpegProcessError) as excinfo:
        run_ffmpeg_with_progress(
            command,
            duration_sec=duration_sec,  # Длительность может быть передана, но ошибка произойдет раньше
            progress_callback=progress_callback,
            process_callback=process_callback,
            check=True  # Ожидаем исключение
        )

    assert excinfo.value.exit_code != 0
    assert "invalid_codec_for_progress" in excinfo.value.stderr  # Проверяем, что ошибка в stderr
    assert excinfo.value.command == command
    assert isinstance(excinfo.value, FfmpegWrapperError)

    # Прогресс мог начать обновляться или нет, в зависимости от того, когда произошла ошибка
    # assert len(progress_values) >= 0 # Просто проверяем, что список создан

    assert not os.path.exists(output_file)  # Файл не должен быть создан


def test_run_ffmpeg_with_progress_cancellation(ffmpeg_path, tmp_output_dir):
    # Тестируем возможность отмены
    input_file = "color=c=blue:s=320x240:d=1000"  # Долгий источник
    output_file = os.path.join(tmp_output_dir, "output_cancel.mkv")  # MKV легче прерывается
    duration_sec = 1000.0

    command = [ffmpeg_path, "-f", "lavfi", "-i", input_file, "-c:v", "copy", output_file]  # Быстрое копирование

    process_obj = None
    is_cancelled = False

    def progress_callback(percentage):
        # В определенный момент запросим отмену
        nonlocal is_cancelled
        if percentage > 5.0 and not is_cancelled:
            is_cancelled = True
            print(f"\n-> Requesting cancellation at {percentage:.1f}%")
            if process_obj:
                try:
                    process_obj.terminate()  # Отправляем сигнал
                    print("-> Terminate signal sent.")
                except Exception as e:
                    print(f"-> Error terminating process: {e}")

    def process_callback(process):
        nonlocal process_obj
        process_obj = process
        print(f"-> Popen process started with PID: {process.pid}")

    # Ожидаем ошибку, т.к. процесс будет прерван
    with pytest.raises(FfmpegProcessError) as excinfo:
        run_ffmpeg_with_progress(
            command,
            duration_sec=duration_sec,
            progress_callback=progress_callback,
            process_callback=process_callback,
            check=True  # Ожидаем, что прерванный процесс вызовет ошибку
        )

    assert excinfo.value.exit_code != 0  # Код должен быть ненулевым (обычно отрицательным)
    # Проверяем, что процесс действительно был прерван (exit code)
    # Проверяем, что файл не был завершен (размер файла меньше ожидаемого?)
    # Проверка размера файла сложна. Просто убедимся, что исключение выброшено.

    print(f"-> FFmpeg run finished with exception: {excinfo.type.__name__}")
