# tests/unit/test_command.py
import pytest
import subprocess  # Импортируем для проверки вывода run
import os
import shlex  # Для парсинга командных строк

# --- Импорты из тестируемой библиотеки ---
from just_ff.command import FFmpegCommandBuilder
from just_ff.exceptions import CommandBuilderError, FfmpegProcessError, FfmpegWrapperError


# --- Конец импортов ---

# Фикстуры ffmpeg_path, tmp_output_dir определены в conftest.py

# --- Тесты для FFmpegCommandBuilder ---

def test_builder_init(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    assert builder.ffmpeg_path == ffmpeg_path
    assert len(builder._global_opts) == 1
    assert builder._global_opts[0] == ("-y", None)  # -y should be added


def test_builder_init_no_overwrite(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=False)
    assert builder.ffmpeg_path == ffmpeg_path
    assert len(builder._global_opts) == 0


def test_builder_reset(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    builder.add_global_option("-loglevel", "info")
    builder.add_input("input1.mp4")
    builder.add_output("output1.mp4")
    builder.map_stream("0:v", "v:0")
    builder.add_filter_complex("split=2[a][b]")
    builder.set_codec("v:0", "libx264")
    builder.add_output("output2.mp4")  # Add second output after some config

    assert len(builder._global_opts) > 1
    assert len(builder._inputs) > 0
    assert len(builder._outputs) > 1  # Should be 2 outputs
    assert len(builder._filters) > 0
    assert len(builder._maps) > 0
    assert len(builder._output_stream_opts) > 0

    builder.reset()

    assert len(builder._global_opts) == 1  # Only -y should remain
    assert builder._global_opts[0] == ("-y", None)
    assert len(builder._inputs) == 0
    assert len(builder._outputs) == 0
    assert len(builder._filters) == 0
    assert builder._filter_complex_script is None
    assert len(builder._maps) == 0
    assert len(builder._output_stream_opts) == 0


def test_add_global_option(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=False)
    builder.add_global_option("-loglevel", "error")
    builder.add_global_option("-stats")
    builder.add_global_option("-nostdin")  # Another flag

    assert len(builder._global_opts) == 3
    assert ("-loglevel", "error") in builder._global_opts
    assert ("-stats", None) in builder._global_opts
    assert ("-nostdin", None) in builder._global_opts


def test_add_global_option_duplicate_flag(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=False)
    builder.add_global_option("-stats")
    builder.add_global_option("-stats")  # Add again

    assert len(builder._global_opts) == 1  # Should only add once


def test_add_input(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    idx0 = builder.add_input("input0.mp4")
    idx1 = builder.add_input("input1.wav", options=["-ss", "5"])
    idx2 = builder.add_input("input2.png", options=["-loop", "1", "-r", "25"])

    assert len(builder._inputs) == 3
    assert idx0 == 0
    assert idx1 == 1
    assert idx2 == 2

    assert builder._inputs[0].path == "input0.mp4"
    assert builder._inputs[0].options == []
    assert builder._inputs[0].input_index == 0

    assert builder._inputs[1].path == "input1.wav"
    assert builder._inputs[1].options == ["-ss", "5"]
    assert builder._inputs[1].input_index == 1

    assert builder._inputs[2].path == "input2.png"
    assert builder._inputs[2].options == ["-loop", "1", "-r", "25"]
    assert builder._inputs[2].input_index == 2


def test_add_input_with_stream_map(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    stream_map = {"sg0_f0_v0": "v:0", "sg0_f0_a0": "a:0"}
    idx = builder.add_input("input.mp4", stream_map=stream_map)

    assert builder._inputs[idx].stream_map == stream_map


def test_add_output(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    idx0 = builder.add_output("output0.mkv")
    idx1 = builder.add_output("output1.mp4", options=["-f", "mp4"])

    assert len(builder._outputs) == 2
    assert idx0 == 0
    assert idx1 == 1

    assert builder._outputs[0].path == "output0.mkv"
    assert builder._outputs[0].options == []
    assert builder._outputs[0].output_index == 0

    assert builder._outputs[1].path == "output1.mp4"
    assert builder._outputs[1].options == ["-f", "mp4"]
    assert builder._outputs[1].output_index == 1

    # Check that map and stream_opts dictionaries are initialized for outputs
    assert 0 in builder._maps
    assert 1 in builder._maps
    assert 0 in builder._output_stream_opts
    assert 1 in builder._output_stream_opts


def test_map_stream(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_input("input.mp4")
    builder.add_output("output.mkv")  # Output 0

    builder.map_stream("0:v:0", "v:0")
    builder.map_stream("0:a:1", "a:1")  # Map second audio to output audio 1
    builder.map_stream("0:s:0", "s:0")

    assert 0 in builder._maps  # Maps for output 0
    assert "v:0" in builder._maps[0] and builder._maps[0]["v:0"] == "0:v:0"
    assert "a:1" in builder._maps[0] and builder._maps[0]["a:1"] == "0:a:1"
    assert "s:0" in builder._maps[0] and builder._maps[0]["s:0"] == "0:s:0"

    # Map to a filter label
    builder.add_filter_complex("[0:v]scale=iw/2:ih/2[v_half]")
    builder.map_stream("[v_half]", "v:0")  # Overwrites previous map for v:0

    assert "v:0" in builder._maps[0] and builder._maps[0]["v:0"] == "[v_half]"  # Should be updated

    # Test multi-output mapping
    builder.add_output("output2.mp4")  # Output 1
    builder.map_stream("0:v:0", "v:0", output_index=1)
    builder.map_stream("0:a:0", "a:0", output_index=1)

    assert 1 in builder._maps  # Maps for output 1
    assert "v:0" in builder._maps[1] and builder._maps[1]["v:0"] == "0:v:0"
    assert "a:0" in builder._maps[1] and builder._maps[1]["a:0"] == "0:a:0"


def test_map_stream_invalid_output_index(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("output.mkv")  # Output 0

    with pytest.raises(CommandBuilderError) as excinfo:
        builder.map_stream("0:v:0", "v:0", output_index=1)  # Output 1 does not exist

    assert "Output index 1 out of range" in str(excinfo.value)


def test_add_filter_complex(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_filter_complex("split=2[a][b]")
    builder.add_filter_complex("[a]scale=iw/2:ih/2[a_half]")

    assert len(builder._filters) == 2
    assert builder._filters[0] == "split=2[a][b]"
    assert builder._filters[1] == "[a]scale=iw/2:ih/2[a_half]"


def test_add_filter_complex_script(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_filter_complex_script("filters.txt")

    assert builder._filter_complex_script == "filters.txt"
    assert len(builder._filters) == 0  # Should be mutually exclusive


def test_add_filter_complex_mutual_exclusion(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_filter_complex("split=2[a][b]")

    with pytest.raises(CommandBuilderError):
        builder.add_filter_complex_script("filters.txt")

    builder2 = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder2.add_filter_complex_script("filters.txt")
    with pytest.raises(CommandBuilderError):
        builder2.add_filter_complex("split=2[a][b]")


def test_set_codec(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("output.mkv")  # Output 0

    builder.set_codec("v:0", "libx264")
    builder.set_codec("a:0", "aac")
    builder.set_codec("s:0", "copy")
    builder.set_codec("a:1", "libopus")  # Second audio stream

    assert 0 in builder._output_stream_opts
    assert "v:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["v:0"] == ["-c:v:0", "libx264"]
    assert "a:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:0"] == ["-c:a:0", "aac"]
    assert "s:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["s:0"] == ["-c:s:0", "copy"]
    assert "a:1" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:1"] == ["-c:a:1", "libopus"]


def test_set_bitrate(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("output.mkv")  # Output 0

    builder.set_bitrate("v:0", "5000k")
    builder.set_bitrate("a:0", "192k")
    builder.set_bitrate("a:1", "0")  # Example for CQ

    assert "v:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["v:0"] == ["-b:v:0", "5000k"]
    assert "a:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:0"] == ["-b:a:0", "192k"]
    assert "a:1" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:1"] == ["-b:a:1", "0"]


def test_set_metadata(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("output.mkv")  # Output 0

    builder.set_metadata("s:v:0", "title", "My Video")
    builder.set_metadata("s:a:1", "language", "rus")
    builder.set_metadata("g", "comment", "Encoded with just-ff")  # Global metadata

    assert "s:v:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["s:v:0"] == ["-metadata:s:v:0", "title=My Video"]
    assert "s:a:1" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["s:a:1"] == ["-metadata:s:a:1", "language=rus"]
    assert "g" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["g"] == ["-metadata:g", "comment=Encoded with just-ff"]


def test_add_output_option(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("output.mkv")  # Output 0

    # General output options
    builder.add_output_option("-movflags", "+faststart")
    builder.add_output_option("-threads", "4")

    # Stream specific options
    builder.add_output_option("-tune", "film", stream_specifier="v:0")
    builder.add_output_option("-af", "aresample=48000", stream_specifier="a:0")
    builder.add_output_option("-disposition", "default", stream_specifier="a:1")  # Flag + value

    assert builder._outputs[0].options == ["-movflags", "+faststart", "-threads", "4"]

    assert "v:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["v:0"] == ["-tune:v:0", "film"]  # Stream specifier added to option name
    assert "a:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:0"] == ["-af:a:0", "aresample=48000"]
    assert "a:1" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:1"] == ["-disposition:a:1", "default"]


def test_add_parsed_options(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_output("output.mkv")  # Output 0

    # General output options string
    builder.add_parsed_options("-movflags +faststart -threads 4")
    assert builder._outputs[0].options == ["-movflags", "+faststart", "-threads", "4"]

    # Stream specific options string
    builder.add_parsed_options("-tune film -x264-params keyint=25", stream_specifier="v:0")
    builder.add_parsed_options("-af aresample=48000 -ac 2", stream_specifier="a:0")
    builder.add_parsed_options("-disposition default", stream_specifier="a:1")

    assert "v:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["v:0"] == ["-tune:v:0", "film", "-x264-params:v:0", "keyint=25"]
    assert "a:0" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:0"] == ["-af:a:0", "aresample=48000", "-ac:a:0", "2"]
    assert "a:1" in builder._output_stream_opts[0]
    assert builder._output_stream_opts[0]["a:1"] == ["-disposition:a:1", "default"]


def test_build_list_basic(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    builder.add_global_option("-loglevel", "error")
    builder.add_input("input.mp4", options=["-ss", "5"])
    builder.add_output("output.mkv")
    builder.map_stream("0:v:0", "v:0")
    builder.set_codec("v:0", "libx264")
    builder.set_bitrate("v:0", "5000k")

    command = builder.build_list()

    # Check basic structure
    assert command[0] == ffmpeg_path
    assert "-y" in command  # From overwrite=True
    assert "-loglevel" in command and "error" in command
    assert "-ss" in command and "5" in command and "-i" in command and "input.mp4" in command
    assert "-map" in command and "0:v:0" in command
    assert "-c:v:0" in command and "libx264" in command
    assert "-b:v:0" in command and "5000k" in command
    assert "output.mkv" in command

    # Check order (approximate, global -> input -> filter -> output)
    # Find indices of key elements
    try:
        idx_y = command.index("-y")
        idx_ss = command.index("-ss")
        idx_i = command.index("-i")
        idx_map = command.index("-map")
        idx_cv0 = command.index("-c:v:0")
        idx_b = command.index("-b:v:0")
        idx_output = command.index("output.mkv")

        assert idx_y < idx_ss  # Global before input options
        assert idx_ss < idx_i  # Input options before -i
        # No filter complex in this test
        # Maps and stream options are output options
        assert idx_map > idx_i  # Maps after input
        assert idx_cv0 > idx_map  # Stream opts after map (order can vary, but after maps is common)
        assert idx_b > idx_cv0 or idx_b > idx_map  # Should be with stream opts
        assert idx_output > idx_b  # Output path is last output argument

    except ValueError as e:
        pytest.fail(f"Command missing expected argument: {e}")


def test_build_list_filters_and_overrides(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_input("input.mp4")
    builder.add_output("output.mkv")  # Output 0

    # Map input video to output v:0 preliminarily
    builder.map_stream("0:v:0", "v:0")
    builder.map_stream("0:a:0", "a:0")

    # Add filters that modify the video stream
    builder.add_filter_complex("[0:v]scale=640:-1[v_scaled]")
    builder.add_filter_complex("[v_scaled]transpose=1[v_transposed]")

    # Override the source for output v:0 to use the filter output
    builder.map_stream("[v_transposed]", "v:0")  # Use map_stream to overwrite

    builder.set_codec("v:0", "libx264")
    builder.set_codec("a:0", "aac")

    command = builder.build_list()
    command_str = " ".join(shlex.quote(arg) for arg in command)

    assert command_str.startswith(shlex.quote(ffmpeg_path))
    assert "-filter_complex" in command
    assert "[0:v]scale=640:-1[v_scaled];[v_scaled]transpose=1[v_transposed]" in command_str  # Filters should be joined
    assert "-map '[v_transposed]'" in command_str  # v:0 should map from filter output
    assert "-map 0:a:0" in command_str  # a:0 should map from original input
    assert "-c:v:0 libx264" in command_str
    assert "-c:a:0 aac" in command_str
    assert shlex.quote("output.mkv") in command_str


def assert_option_value(args_list: list, option: str, expected_value: str, message: str = ""):
    """Helper to assert that an option is followed by its expected value."""
    try:
        idx = args_list.index(option)
        actual_value = args_list[idx + 1]
        assert actual_value == expected_value, \
            f"{message} Option '{option}' found, but value '{actual_value}' != expected '{expected_value}' in {args_list}"
    except ValueError:
        pytest.fail(f"{message} Option '{option}' not found in {args_list}")
    except IndexError:
        pytest.fail(f"{message} Option '{option}' found at end of list, no value, in {args_list}")


def test_build_list_multi_output(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)  # -y is added by default
    builder.add_input("input.mp4")
    builder.add_output("output1.mkv")  # Output 0
    builder.add_output("output2.mp4")  # Output 1

    # Mapping for output 0
    builder.map_stream("0:v:0", "v:0", output_index=0)
    builder.map_stream("0:a:0", "a:0", output_index=0)
    builder.set_codec("v:0", "libx264", output_index=0)
    builder.set_codec("a:0", "aac", output_index=0)

    # Mapping for output 1
    builder.map_stream("0:v:0", "v:0", output_index=1)  # Target v:0 for output 1
    builder.map_stream("0:a:1", "a:0", output_index=1)  # Target a:0 for output 1 (from source 0:a:1)
    builder.set_codec("v:0", "libvpx-vp9", output_index=1)  # For target v:0 of output 1
    builder.set_codec("a:0", "libopus", output_index=1)  # For target a:0 of output 1
    builder.add_output_option("-f", "mp4", output_index=1)

    command_list = builder.build_list()
    # print(f"\nGenerated command for multi_output: {' '.join(shlex.quote(arg) for arg in command_list)}")

    try:
        output1_path_idx = command_list.index("output1.mkv")
        output2_path_idx = command_list.index("output2.mp4")
    except ValueError:
        pytest.fail("Output paths not found in command list.")

    # Determine the start of output options (after globals, inputs, filters)
    # Simplified approach: find first -map or output-specific option if robust slicing is hard.
    # For this specific test, the first map should belong to output1.
    try:
        first_map_idx = command_list.index("-map")
    except ValueError:
        pytest.fail("'-map' option not found, cannot reliably slice for output blocks.")

    # Args for output 0 (from first map up to, but not including, its path)
    # The build_output_args places maps, then stream_opts, then general_opts, then path
    # So, the slice for options is [first_map_idx : output1_path_idx]
    output1_options_block = command_list[first_map_idx: output1_path_idx]

    # Args for output 1 (from after output1_path up to, but not including, its path)
    output2_options_block = command_list[output1_path_idx + 1: output2_path_idx]

    # print(f"Output 1 options block: {output1_options_block}")
    # print(f"Output 2 options block: {output2_options_block}")

    # Check output 0 arguments
    # Expected order due to sort_key: v:0 maps/opts, then a:0 maps/opts
    assert "-map" in output1_options_block  # General check
    # More specific map checks (order might vary based on map_stream calls if not sorted robustly by target)
    # The builder sorts map keys by stream_specifier_sort_key, so v:0 then a:0
    map_0v0_idx_out1 = output1_options_block.index("-map")
    assert output1_options_block[map_0v0_idx_out1 + 1] == "0:v:0"
    map_0a0_idx_out1 = output1_options_block.index("-map", map_0v0_idx_out1 + 2)  # Search after previous map
    assert output1_options_block[map_0a0_idx_out1 + 1] == "0:a:0"

    assert_option_value(output1_options_block, "-c:v:0", "libx264", "Output 1")
    assert_option_value(output1_options_block, "-c:a:0", "aac", "Output 1")
    assert "-f" not in output1_options_block  # Format option should be with output 1

    # Check output 1 arguments
    assert "-map" in output2_options_block
    # Maps for output 1 (target v:0 from source 0:v:0, target a:0 from source 0:a:1)
    # Sorted by target specifier: v:0 then a:0
    map_0v0_idx_out2 = output2_options_block.index("-map")
    assert output2_options_block[map_0v0_idx_out2 + 1] == "0:v:0"  # Source for v:0
    map_0a1_idx_out2 = output2_options_block.index("-map", map_0v0_idx_out2 + 2)
    assert output2_options_block[map_0a1_idx_out2 + 1] == "0:a:1"  # Source for a:0 is 0:a:1

    assert_option_value(output2_options_block, "-c:v:0", "libvpx-vp9", "Output 2")
    assert_option_value(output2_options_block, "-c:a:0", "libopus", "Output 2")
    assert_option_value(output2_options_block, "-f", "mp4", "Output 2")


def test_build_no_outputs(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_input("input.mp4")  # Input added, but no output

    with pytest.raises(CommandBuilderError) as excinfo:
        builder.build_list()

    assert "No outputs defined" in str(excinfo.value)


def test_build_no_inputs_with_filter(ffmpeg_path):
    # Test using lavfi source which doesn't require -i
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_filter_complex("color=c=red:s=320x240:d=5[out]")
    builder.map_stream("[out]", "v:0")
    builder.set_codec("v:0", "libx264")
    builder.add_output("output.mp4")

    command_list = builder.build_list()
    command_str = " ".join(shlex.quote(arg) for arg in command_list)

    assert "-filter_complex" in command_str
    assert "color=c=red:s=320x240:d=5[out]" in command_str
    assert "-map [out]" in command_str
    assert "-i" not in command_str  # No -i input
    assert shlex.quote("output.mp4") in command_str


def test_build_with_metadata(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_input("input.mp4")
    builder.add_output("output.mkv")
    builder.map_stream("0:v:0", "v:0")
    builder.map_stream("0:a:0", "a:0")

    builder.set_metadata("s:v:0", "title", "My Video Title")
    builder.set_metadata("s:a:0", "language", "eng")
    builder.set_metadata("g", "comment", "Test Comment")  # Global metadata

    command_list = builder.build_list()
    command_str = " ".join(shlex.quote(arg) for arg in command_list)

    assert "-metadata:s:v:0 title=My Video Title" in command_str  # Note: shlex.quote handles spaces
    assert "-metadata:s:a:0 language=eng" in command_str
    assert "-metadata:g comment=Test Comment" in command_str


def test_build_with_add_parsed_options(ffmpeg_path):
    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path)
    builder.add_input("input.mp4")
    builder.add_output("output.mkv")

    builder.map_stream("0:v:0", "v:0")
    builder.set_codec("v:0", "libx264")
    builder.set_bitrate("v:0", "5000k")

    # Add parsed general output options
    builder.add_parsed_options("-movflags +faststart -strict -2")

    # Add parsed stream options
    builder.map_stream("0:a:0", "a:0")
    builder.set_codec("a:0", "aac")
    builder.add_parsed_options("-af aresample=48000 -ac 2", stream_specifier="a:0")

    command_list = builder.build_list()
    command_str = " ".join(shlex.quote(arg) for arg in command_list)

    assert "-movflags +faststart" in command_str
    assert "-strict -2" in command_str  # Added after movflags

    # Stream options added with specifier
    assert "-af:a:0 aresample=48000" in command_str
    assert "-ac:a:0 2" in command_str


# --- Тесты для метода run ---

def test_run_success(ffmpeg_path, tmp_output_dir):
    # Тестируем успешный запуск через builder.run()
    # Создаем простой файл (например, lavfi source)
    output_file = os.path.join(tmp_output_dir, "test_run_success.mp4")
    duration_sec = 1.0

    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    builder.add_filter_complex("color=c=green:s=320x240:d=1[out]")
    builder.map_stream("[out]", "v:0")
    builder.set_codec("v:0", "libx264")  # Использование x264 гарантирует кодирование
    builder.add_output(output_file)

    progress_values = []
    process_obj = None

    def progress_callback(percentage): progress_values.append(percentage)

    def process_callback(process): nonlocal process_obj; process_obj = process

    result = builder.run(
        duration_sec=duration_sec,
        progress_callback=progress_callback,
        process_callback=process_callback,
        check=True  # Ожидаем успех
    )

    assert result is True
    assert os.path.exists(output_file)
    assert os.path.getsize(output_file) > 0
    assert len(progress_values) > 0  # Прогресс должен был быть
    assert progress_values[-1] == 100.0


def test_run_failure(ffmpeg_path, tmp_output_dir):
    # Тестируем ошибку запуска через builder.run()
    # Использование невалидного кодека
    output_file = os.path.join(tmp_output_dir, "test_run_fail.mp4")
    duration_sec = 1.0

    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    builder.add_filter_complex("color=c=red:s=320x240:d=1[out]")
    builder.map_stream("[out]", "v:0")
    builder.set_codec("v:0", "non_existent_codec")  # Невалидный кодек
    builder.add_output(output_file)

    progress_values = []
    process_obj = None

    def progress_callback(percentage): progress_values.append(percentage)

    def process_callback(process): nonlocal process_obj; process_obj = process

    with pytest.raises(FfmpegProcessError) as excinfo:
        builder.run(
            duration_sec=duration_sec,
            progress_callback=progress_callback,
            process_callback=process_callback,
            check=True
        )

    assert excinfo.value.exit_code != 0
    assert "non_existent_codec" in excinfo.value.stderr  # Ошибка в stderr
    assert not os.path.exists(output_file)  # Файл не должен быть создан


def test_run_cancellation(ffmpeg_path, tmp_output_dir):
    # Тестируем отмену через builder.run()
    output_file = os.path.join(tmp_output_dir, "test_run_cancel.mkv")
    duration_sec = 100.0  # Долгая операция

    builder = FFmpegCommandBuilder(ffmpeg_path=ffmpeg_path, overwrite=True)
    builder.add_filter_complex("color=c=blue:s=320x240:d=100[out]")  # 100 сек
    builder.map_stream("[out]", "v:0")
    builder.set_codec("v:0", "copy")  # Быстрое копирование
    builder.add_output(output_file)

    process_obj = None
    cancel_called = False

    def progress_callback(percentage):
        nonlocal cancel_called
        if percentage > 5.0 and not cancel_called:
            cancel_called = True
            print(f"\n-> Test cancelling at {percentage:.1f}%")
            if process_obj:
                try:
                    process_obj.terminate()  # Отправляем сигнал
                except:
                    pass

    def process_callback(process):
        nonlocal process_obj
        process_obj = process
        print(f"-> Popen process started with PID: {process.pid}")

    with pytest.raises(FfmpegProcessError) as excinfo:
        builder.run(
            duration_sec=duration_sec,
            progress_callback=progress_callback,
            process_callback=process_callback,
            check=True
        )

    assert excinfo.value.exit_code != 0  # Должен быть ненулевой код выхода после прерывания
    # assert os.path.exists(output_file) # Файл может существовать, но быть неполным/поврежденным
