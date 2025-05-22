# tests/unit/test_probe.py
import pytest
import os
import json  # Импортируем json для проверки структуры

# --- Импорты из тестируемой библиотеки ---
from just_ff.probe import FFprobeRunner
from just_ff.streams import MediaInfo, FormatInfo, StreamInfo
from just_ff.exceptions import (
    FfmpegWrapperError,
    FfmpegExecutableNotFoundError,
    FfmpegProcessError,
    FfprobeJsonError,
)


# --- Конец импортов ---

# Фикстуры ffprobe_path, video_mp4, audio_aac, image_png, subtitle_srt определены в conftest.py


def test_ffprobe_runner_init(ffprobe_path):
    # Тестируем инициализацию
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    assert runner.ffprobe_path == ffprobe_path


def test_run_ffprobe_success(ffprobe_path):
    # Для -version, вывод не JSON. run_ffprobe ожидает JSON.
    # Изменим тест, чтобы он запускал команду, которая *действительно* выдает JSON.
    # Проверка версии лучше делается в фикстуре или в run_command.
    # Тестируем run_ffprobe с командой, которая выдает JSON
    args_json = ["-show_format", "-i", os.path.join(os.path.dirname(__file__),
                                                    "dummy.txt")]  # Используем несуществующий файл для проверки ошибки
    # dummy.txt не должен существовать, чтобы FFprobe выдал ошибку, но в формате JSON об ошибке.
    # Или лучше использовать реальный файл? Да, лучше реальный.
    # Используем фикстуру тестового файла (video_mp4)
    # Это будет тестом на run_ffprobe при успешном анализе файла.

    # Используем фикстуру video_mp4
    # runner = FFprobeRunner(ffprobe_path=ffprobe_path) # runner уже создан в начале
    # args_json_real = ["-show_format", "-i", video_mp4] # Недоступно здесь напрямую

    # Используем простую команду с lavfi source, которая выдает JSON формат инфо
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    args_json_lavfi = ["-show_format", "-f", "lavfi", "-i", "color=d=1"]  # Длительность 1 сек
    result_dict_lavfi = runner.run_ffprobe(args_json_lavfi)

    assert isinstance(result_dict_lavfi, dict)
    assert "format" in result_dict_lavfi


def test_run_ffprobe_not_found():
    # Тестируем ошибку FileNotFoundError
    runner = FFprobeRunner(ffprobe_path="non_existent_ffprobe")
    args = ["-show_format", "-i", "dummy.mp4"]
    with pytest.raises(FfmpegExecutableNotFoundError) as excinfo:
        runner.run_ffprobe(args)

    assert "non_existent_ffprobe" in str(excinfo.value)


def test_run_ffprobe_failure(ffprobe_path):
    # Тестируем ошибку выполнения (несуществующий файл ввода)
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    args = ["-show_format", "-i", "non_existent_file.mp4"]
    with pytest.raises(FfmpegProcessError) as excinfo:
        runner.run_ffprobe(args)

    assert excinfo.value.exit_code != 0  # ffprobe должен вернуть ошибку
    assert "non_existent_file.mp4" in excinfo.value.stderr  # Проверяем сообщение об ошибке
    assert "No such file or directory" in excinfo.value.stderr or "Invalid argument" in excinfo.value.stderr  # Типичный вывод ошибки


def test_run_ffprobe_json_error(ffprobe_path):
    # Тестируем ошибку парсинга JSON (например, принудительный вывод в другом формате)
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    # Пробуем получить вывод в формате ini, который не JSON
    args = ["-print_format", "ini", "-show_format", "-i", os.path.join(os.path.dirname(__file__),
                                                                       "dummy.txt")]  # Используем файл-заглушку, чтобы не анализировать реальный
    # dummy.txt не должен существовать, чтобы не было анализа, но команда запустилась
    # Лучше использовать lavfi source, которая выдаст ini
    args_ini = ["-print_format", "ini", "-show_format", "-f", "lavfi", "-i", "color=d=1"]

    with pytest.raises(FfprobeJsonError) as excinfo:
        runner.run_ffprobe(args_ini)

    assert isinstance(excinfo.value, FfmpegWrapperError)  # Проверяем наследование
    assert "Failed to decode ffprobe JSON output" in str(excinfo.value)
    assert "[format]" in excinfo.value.stdout  # Проверяем, что ini-вывод есть в stdout


# --- Тесты для get_media_info ---
def test_get_media_info_success(ffprobe_path, video_mp4):
    # Тестируем успешный анализ реального файла
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    media_info = runner.get_media_info(video_mp4)

    assert isinstance(media_info, MediaInfo)
    assert isinstance(media_info.format, FormatInfo)
    assert isinstance(media_info.streams, list)
    assert len(media_info.streams) > 0  # У видео должны быть потоки

    # Проверяем некоторые поля
    assert media_info.format.filename.endswith(
        os.path.basename(video_mp4))  # Проверяем, что filename в формате правильный
    assert media_info.format.format_name is not None
    assert media_info.streams[0].codec_type == "video"
    assert media_info.streams[0].width is not None
    assert media_info.streams[0].height is not None
    assert media_info.raw_dict is not None  # raw_dict должен быть заполнен
    assert not media_info.stream_id_map  # map должен быть пустым по умолчанию

    # Проверяем, что from_dict работает корректно для вложенных объектов
    assert isinstance(media_info.streams[0].tags, dict)
    assert isinstance(media_info.streams[0].disposition, dict)


def test_get_media_info_file_not_found(ffprobe_path):
    # Тестируем ошибку FileNotFoundError при анализе
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    with pytest.raises(FileNotFoundError) as excinfo:
        runner.get_media_info("non_existent_file_for_analysis.mp4")

    assert "Input file not found" in str(excinfo.value)


def test_get_media_info_ffprobe_failure(ffprobe_path):
    # Тестируем ошибку ffprobe при анализе (например, поврежденный файл, который вызывает ошибку)
    # Создадим временный "поврежденный" файл
    corrupt_file_path = os.path.join(os.path.dirname(__file__), "corrupt.mp4")
    with open(corrupt_file_path, "w") as f:
        f.write("This is not a video file.")

    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    with pytest.raises(FfmpegProcessError) as excinfo:
        runner.get_media_info(corrupt_file_path)

    assert excinfo.value.exit_code != 0
    assert "Invalid data found" in excinfo.value.stderr
    # Проверяем, что исключение обернуто
    assert isinstance(excinfo.value, FfmpegWrapperError)

    os.remove(corrupt_file_path)  # Удаляем временный файл


# --- Тесты для get_duration ---
def test_get_duration_success(ffprobe_path, video_mp4, audio_aac, image_png, subtitle_srt):
    # Тестируем получение длительности для разных типов файлов
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)

    # Видео файл
    duration_video = runner.get_duration(video_mp4)
    assert isinstance(duration_video, float)
    assert duration_video > 0  # Длительность должна быть положительной
    # print(f"\nDuration of {os.path.basename(video_mp4)}: {duration_video:.2f}s") # Отладка

    # Аудио файл
    duration_audio = runner.get_duration(audio_aac)
    assert isinstance(duration_audio, float)
    assert duration_audio > 0
    # print(f"\nDuration of {os.path.basename(audio_aac)}: {duration_audio:.2f}s") # Отладка

    # Изображение (не должно иметь длительности)
    duration_image = runner.get_duration(image_png)
    assert duration_image is None

    # Субтитры (обычно не имеют длительности формата/стрима)
    duration_subtitle = runner.get_duration(subtitle_srt)
    assert duration_subtitle is None


def test_get_duration_file_not_found(ffprobe_path):
    # Тестируем FileNotFoundError
    runner = FFprobeRunner(ffprobe_path=ffprobe_path)
    with pytest.raises(FileNotFoundError) as excinfo:
        runner.get_duration("non_existent_file_for_duration.mp4")

    assert "Input file not found" in str(excinfo.value)
