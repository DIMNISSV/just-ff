# tests/unit/test_streams.py
import pytest
import json

# --- Импорты из тестируемой библиотеки ---
from just_ff.streams import StreamInfo, FormatInfo, MediaInfo, safe_float, safe_int

# --- Конец импортов ---

# Пример минимального ffprobe stream dict для теста
MINIMAL_STREAM_DICT = {
    "index": 0,
    "codec_name": "h264",
    "codec_type": "video",
    "width": 1920,
    "height": 1080,
    "r_frame_rate": "25/1",
    "time_base": "1/90000",
    "duration_ts": 2700000,
    "duration": 30.000,
    "tags": {"language": "eng", "title": "Video Track"}
}

# Пример минимального ffprobe format dict для теста
MINIMAL_FORMAT_DICT = {
    "filename": "test.mp4",
    "nb_streams": 1,
    "format_name": "mp4",
    "duration": 30.000,
    "size": 123456,
    "tags": {"encoder": "Lavf58.29.100"}
}

# Пример минимального полного ffprobe dict
MINIMAL_FFPROBE_DICT = {
    "programs": [],
    "streams": [MINIMAL_STREAM_DICT],
    "format": MINIMAL_FORMAT_DICT
}


def test_safe_float():
    assert safe_float("123.45") == 123.45
    assert safe_float("10") == 10.0
    assert safe_float(100) == 100.0
    assert safe_float(None) is None
    assert safe_float("invalid") is None
    assert safe_float("invalid", default=0.0) == 0.0
    assert safe_float(None, default=5.0) == 5.0


def test_safe_int():
    assert safe_int("123") == 123
    assert safe_int("10.0") == 10
    assert safe_int(100) == 100
    assert safe_int(None) is None
    assert safe_int("invalid") is None
    assert safe_int("invalid", default=0) == 0
    assert safe_int(None, default=5) == 5
    assert safe_int(123.45) == 123  # Should handle floats


def test_stream_info_from_dict():
    stream = StreamInfo.from_dict(MINIMAL_STREAM_DICT)

    assert isinstance(stream, StreamInfo)
    assert stream.index == 0
    assert stream.codec_name == "h264"
    assert stream.codec_type == "video"
    assert stream.width == 1920
    assert stream.height == 1080
    assert stream.duration == 30.000
    assert stream.language == "eng"
    assert stream.title == "Video Track"
    assert stream.unique_id == ""  # Should not be set by from_dict

    # Test properties
    assert stream.duration_sec == 30.000
    assert stream.frame_rate_float == 25.0  # From r_frame_rate
    assert not stream.is_default  # disposition not set as default

    # Test with missing optional fields
    minimal_audio = {
        "index": 1, "codec_name": "aac", "codec_type": "audio",
        "sample_rate": 44100, "channels": 2, "time_base": "1/44100",
        "disposition": {"default": 1}  # Example disposition
    }
    audio_stream = StreamInfo.from_dict(minimal_audio)
    assert audio_stream.index == 1
    assert audio_stream.codec_type == "audio"
    assert audio_stream.width is None  # Video specific
    assert audio_stream.sample_rate == 44100
    assert audio_stream.channels == 2
    assert audio_stream.is_default

    # Test duration calculation fallback (if 'duration' is missing)
    stream_no_duration_field = MINIMAL_STREAM_DICT.copy()
    del stream_no_duration_field["duration"]
    stream_no_duration = StreamInfo.from_dict(stream_no_duration_field)
    assert stream_no_duration.duration is None  # Field is None
    # Calculation from duration_ts and time_base
    # duration_ts = 2700000, time_base = "1/90000" -> 2700000 * (1/90000) = 30.0
    assert stream_no_duration.duration_sec == 30.0

    # Test with invalid duration/time_base
    stream_bad_time = StreamInfo.from_dict({"index": 0, "duration_ts": 100, "time_base": "invalid"})
    assert stream_bad_time.duration_sec is None


def test_format_info_from_dict():
    format_info = FormatInfo.from_dict(MINIMAL_FORMAT_DICT)

    assert isinstance(format_info, FormatInfo)
    assert format_info.filename == "test.mp4"
    assert format_info.format_name == "mp4"
    assert format_info.duration == 30.000
    assert format_info.size == 123456
    assert format_info.duration_sec == 30.000

    # Test with missing optional fields
    minimal_format_simple = {"filename": "simple.wav", "format_name": "wav"}
    format_simple = FormatInfo.from_dict(minimal_format_simple)
    assert format_simple.filename == "simple.wav"
    assert format_simple.duration is None  # Optional field missing
    assert format_simple.duration_sec is None  # Property reflects missing field


def test_media_info_from_ffprobe_dict():
    media_info = MediaInfo.from_ffprobe_dict(MINIMAL_FFPROBE_DICT)

    assert isinstance(media_info, MediaInfo)
    assert isinstance(media_info.format, FormatInfo)
    assert len(media_info.streams) == 1
    assert isinstance(media_info.streams[0], StreamInfo)

    # Check data integrity
    assert media_info.format.filename == "test.mp4"
    assert media_info.streams[0].codec_name == "h264"
    assert media_info.streams[0].width == 1920

    # Check fields not part of __init__
    assert media_info.raw_dict == MINIMAL_FFPROBE_DICT
    assert not media_info.stream_id_map  # Should be empty initially

    # Test update_stream_id_map (needs unique_id assigned first, which is done externally)
    # Simulate assigning unique_id
    media_info.streams[0].unique_id = "sg0_f0_v0"
    media_info.update_stream_id_map()
    assert "sg0_f0_v0" in media_info.stream_id_map
    assert media_info.stream_id_map["sg0_f0_v0"] is media_info.streams[0]


def test_media_info_get_stream():
    media_info = MediaInfo.from_ffprobe_dict({
        "streams": [
            {"index": 0, "codec_type": "video"},
            {"index": 1, "codec_type": "audio"},
            {"index": 2, "codec_type": "subtitle"},
        ]
    })
    assert media_info.get_stream(0) is not None
    assert media_info.get_stream(0).codec_type == "video"
    assert media_info.get_stream(1) is not None
    assert media_info.get_stream(1).codec_type == "audio"
    assert media_info.get_stream(3) is None  # Non-existent index


def test_media_info_get_streams_by_type():
    media_info = MediaInfo.from_ffprobe_dict({
        "streams": [
            {"index": 0, "codec_type": "video"},
            {"index": 1, "codec_type": "audio"},
            {"index": 2, "codec_type": "audio"},
            {"index": 3, "codec_type": "subtitle"},
        ]
    })
    video_streams = media_info.get_streams_by_type("video")
    audio_streams = media_info.get_streams_by_type("audio")
    subtitle_streams = media_info.get_streams_by_type("subtitle")
    data_streams = media_info.get_streams_by_type("data")

    assert len(video_streams) == 1
    assert video_streams[0].index == 0
    assert len(audio_streams) == 2
    assert {s.index for s in audio_streams} == {1, 2}
    assert len(subtitle_streams) == 1
    assert subtitle_streams[0].index == 3
    assert len(data_streams) == 0  # Should be empty list
