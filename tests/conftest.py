# tests/conftest.py
import pytest
import os
import shutil
import subprocess  # Импортируем для проверки наличия ffmpeg/ffprobe


# --- Проверка наличия FFmpeg/FFprobe ---
# Проверяем один раз при старте тестов
@pytest.fixture(scope="session")
def ffmpeg_path():
    """Fixture to get the ffmpeg executable path and check its availability."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg executable not found in PATH.")
    # Опционально, проверить, что это рабочая версия
    try:
        subprocess.run([ffmpeg, "-version"], check=True, capture_output=True, timeout=5)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip(f"FFmpeg executable found at '{ffmpeg}' but seems non-functional.")

    return ffmpeg


@pytest.fixture(scope="session")
def ffprobe_path():
    """Fixture to get the ffprobe executable path and check its availability."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        pytest.skip("FFprobe executable not found in PATH.")
    # Опционально, проверить, что это рабочая версия
    try:
        subprocess.run([ffprobe, "-version"], check=True, capture_output=True, timeout=5)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip(f"FFprobe executable found at '{ffprobe}' but seems non-functional.")
    return ffprobe


# --- Пути к тестовым файлам ---
@pytest.fixture(scope="session")
def assets_dir():
    """Fixture for the path to the assets directory."""
    # Предполагаем, что папка assets/ находится в корне проекта
    current_dir = os.path.dirname(os.path.abspath(__file__))  # .../just-ff/tests
    project_root = os.path.dirname(current_dir)  # .../just-ff/
    assets = os.path.join(project_root, "assets")
    if not os.path.isdir(assets):
        pytest.skip(f"Assets directory not found at: {assets}")
    # Проверяем, что папка не пустая
    if not any(os.path.isfile(os.path.join(assets, f)) for f in os.listdir(assets)):
        pytest.skip(f"Assets directory '{assets}' is empty.")
    return assets


# Пример фикстуры для конкретного тестового файла
@pytest.fixture(scope="session")
def video_mp4(assets_dir):
    """Path to a test MP4 video file."""
    file_path = os.path.join(assets_dir, "video.mp4")  # Предполагаем наличие video.mp4
    if not os.path.isfile(file_path):
        pytest.skip(f"Test file not found: {file_path}")
    return file_path


@pytest.fixture(scope="session")
def audio_aac(assets_dir):
    """Path to a test AAC audio file."""
    file_path = os.path.join(assets_dir, "audio.aac")  # Предполагаем наличие audio.aac
    if not os.path.isfile(file_path):
        pytest.skip(f"Test file not found: {file_path}")
    return file_path


@pytest.fixture(scope="session")
def image_png(assets_dir):
    """Path to a test PNG image file."""
    file_path = os.path.join(assets_dir, "image.png")  # Предполагаем наличие image.png
    if not os.path.isfile(file_path):
        pytest.skip(f"Test file not found: {file_path}")
    return file_path


@pytest.fixture(scope="session")
def subtitle_srt(assets_dir):
    """Path to a test SRT subtitle file."""
    file_path = os.path.join(assets_dir, "subtitle.srt")  # Предполагаем наличие subtitle.srt
    if not os.path.isfile(file_path):
        pytest.skip(f"Test file not found: {file_path}")
    return file_path


# --- Фикстура для временной директории ---
@pytest.fixture
def tmp_output_dir(tmp_path):
    """Provides a temporary directory for output files."""
    # tmp_path is a built-in pytest fixture providing a temporary directory
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    return str(output_dir)
