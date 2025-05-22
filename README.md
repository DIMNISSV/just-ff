# just-ff

A Python wrapper library for the FFmpeg and FFprobe command-line utilities.

![GitHub Tag](https://img.shields.io/github/v/tag/DIMNISSV/just-ff)
![License](https://img.shields.io/github/license/DIMNISSV/just-ff) 
![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![ffmpeg Version](https://img.shields.io/badge/ffmpeg-7.0%2B-darkgreen.svg)
## Introduction

`just-ff` provides a clean, Pythonic interface to interact with FFmpeg and FFprobe, making it easier to integrate media processing and analysis into your Python applications without directly managing subprocess calls and complex command-line arguments. It aims to be a robust and flexible wrapper, separating the concerns of command building, process execution, and output parsing.

## Features

-   Run `ffprobe` to get detailed media information (`MediaInfo`, `StreamInfo`, `FormatInfo`).
-   Build complex `ffmpeg` command-lines programmatically using a builder pattern (`FFmpegCommandBuilder`).
-   Run `ffmpeg` commands with real-time percentage progress reporting.
-   Handle errors from FFmpeg/FFprobe processes with specific exceptions.
-   Minimal dependencies (primarily `subprocess`, `json`, `re`, `typing`, `dataclasses` from standard library).

## Installation

You can install `just-ff` in several ways:

### From GitHub (latest development version)

**Using pip:**

```bash
pip install git+https://github.com/DIMNISSV/just-ff.git
```

**Using Poetry:**

```bash
poetry add git+https://github.com/DIMNISSV/just-ff.git
```

**Or, by cloning and installing with Poetry:**

```bash
git clone https://github.com/DIMNISSV/just-ff.git
cd just-ff
poetry install
```

### FFMPEG

Make sure you have [FFMPEG](https://ffmpeg.org/download.html) installed and accessible in your system's PATH.
`just-ff` is a wrapper, it does **not** include the FFmpeg binaries.

### Python

Make sure you have [Python](https://www.python.org/downloads/) installed and accessible in your system's PATH.

## Documentation

### `just_ff.probe.FFprobeRunner`

Class to run `ffprobe` commands and parse output into structured data.

```python
from just_ff import FFprobeRunner, FfmpegWrapperError, FileNotFoundError

# Initialize the runner (defaults to 'ffprobe' in PATH)
# You can specify a custom path: FFprobeRunner(ffprobe_path="/path/to/ffprobe")
ffprobe = FFprobeRunner()

# Get comprehensive media information
try:
    media_info = ffprobe.get_media_info("path/to/your/video.mp4")

    print(f"File: {media_info.format.filename}")
    print(f"Format: {media_info.format.format_name}")
    print(f"Duration: {media_info.format.duration_sec:.2f} seconds")
    print(f"Total Streams: {len(media_info.streams)}")

    for i, stream in enumerate(media_info.streams):
        print(f"  Stream #{stream.index}: Type={stream.codec_type}, Codec={stream.codec_name}")
        if stream.codec_type == 'video':
            print(f"    Resolution: {stream.width}x{stream.height}, FPS: {stream.frame_rate_float:.2f}")
        elif stream.codec_type == 'audio':
             print(f"    Channels: {stream.channels}, Layout: {stream.channel_layout}, Sample Rate: {stream.sample_rate}")
             print(f"    Bitrate: {stream.bit_rate / 1000 if stream.bit_rate else 'N/A'} kb/s")
        if stream.language:
             print(f"    Language: {stream.language}")
        if stream.title:
             print(f"    Title: {stream.title}")

except FileNotFoundError:
    print("Error: Input file not found.")
except FfmpegWrapperError as e:
    print(f"FFprobe Error: {e}")
    # Access specific error info if needed
    # if isinstance(e, FfmpegProcessError):
    #     print(f"Stderr:\n{e.stderr}")

# Get just the duration
try:
    duration = ffprobe.get_duration("path/to/your/audio.aac")
    if duration is not None:
        print(f"Duration: {duration:.2f} seconds")
    else:
        print("Could not determine duration.")

except FfmpegWrapperError as e:
    print(f"FFprobe Error: {e}")
```

### `just_ff.command.FFmpegCommandBuilder`

Class to programmatically build complex `ffmpeg` command arguments.

```python
from just_ff import FFmpegCommandBuilder, FfmpegWrapperError, FfmpegProcessError
import os # For output file paths

# Initialize the builder (defaults to 'ffmpeg' in PATH)
# overwrite=True adds -y by default
ffmpeg = FFmpegCommandBuilder(overwrite=True)
# You can specify a custom path: FFmpegCommandBuilder(ffmpeg_path="/path/to/ffmpeg")

# --- Add Global Options ---
ffmpeg.add_global_option("-loglevel", "info")
ffmpeg.add_global_option("-stats")

# --- Add Input Files ---
# add_input returns the input index (0-based)
input1_idx = ffmpeg.add_input("path/to/input1.mp4", options=["-ss", "5"]) # Start input1 from 5s
input2_idx = ffmpeg.add_input("path/to/input2.wav")
input3_idx = ffmpeg.add_input("path/to/overlay.png", options=["-loop", "1", "-r", "25"]) # Loop image at 25 fps

# --- Add Filter Complex (Optional) ---
# Filtergraph string using input stream specifiers (e.g., [0:v]) and output labels (e.g., [v_out])
filter_graph = f"[{input1_idx}:v][{input3_idx}:v] overlay=x='mod(t,W)':enable='gte(t,2)':shortest=0 [v_out];" # Overlay image
filter_graph += f"[{input2_idx}:a][{input1_idx}:a] amerge=inputs=2 [a_merged]" # Merge audio from input1 and input2
ffmpeg.add_filter_complex(filter_graph)

# --- Add Output Files ---
# add_output returns the output index (usually 0 for the first output)
output1_idx = ffmpeg.add_output("path/to/output/video.mp4")
# You can add multiple outputs:
# output2_idx = ffmpeg.add_output("path/to/output/audio.aac")

# --- Map Streams to Outputs ---
# Map using map_stream(source_specifier, output_stream_specifier, output_index=0)
# Source can be an input specifier (InputIndex:StreamType:StreamIndex, e.g., "0:v:0")
# or a filter output label (e.g., "[v_out]").
# Output stream specifier is type:index (e.g., "v:0", "a:1").
ffmpeg.map_stream("[v_out]", "v:0", output_index=output1_idx) # Map filter output to output video stream 0
ffmpeg.map_stream("[a_merged]", "a:0", output_index=output1_idx) # Map merged audio filter output to output audio stream 0
# ffmpeg.map_stream(f"{input1_idx}:s:0", "s:0", output_index=output1_idx) # Map subtitle from input1

# --- Set Stream-Specific Output Options (Codecs, Bitrates, Metadata) ---
# Use set_codec, set_bitrate, set_metadata, add_output_option
# Arguments include output_stream_specifier (e.g., "v:0", "a:0") and output_index (default 0)

# Video settings for output stream v:0 of output 0
ffmpeg.set_codec("v:0", "libx264", output_index=output1_idx)
ffmpeg.add_output_option("-preset", "medium", stream_specifier="v:0", output_index=output1_idx)
ffmpeg.set_bitrate("v:0", "5000k", output_index=output1_idx) # Overrides CRF if > 0
# Or use CRF: ffmpeg.add_output_option("-crf", "23", stream_specifier="v:0", output_index=output1_idx)

# Audio settings for output stream a:0 of output 0
ffmpeg.set_codec("a:0", "aac", output_index=output1_idx)
ffmpeg.set_bitrate("a:0", "192k", output_index=output1_idx)
ffmpeg.set_metadata("s:a:0", "language", "eng", output_index=output1_idx) # Metadata for stream a:0

# Global metadata for output 0
ffmpeg.set_metadata("g", "title", "My Converted Video", output_index=output1_idx)

# --- Add General Output Options (e.g., container flags) ---
# Use add_output_option(option, value, output_index=0)
ffmpeg.add_output_option("-movflags", "+faststart", output_index=output1_idx)
# You can also parse a string of options:
# ffmpeg.add_parsed_options("-movflags +faststart -strict -2", output_index=output1_idx)

# --- Build the command ---
command_list = ffmpeg.build_list()
command_string = ffmpeg.build() # Gets command as a string (with shlex.quote)

print("Generated Command List:")
print(command_list)
print("\nGenerated Command String:")
print(command_string)


# --- Run the command ---
# You need the duration of the *source* file(s) for progress reporting.
# If using multiple inputs and complex filters, duration calculation for progress can be tricky.
# For simple cases (single input or concat), use ffprobe on the input.
try:
    # Get duration of the main input for progress (assuming input1.mp4 is main)
    # Requires FFprobeRunner
    # from just_ff import FFprobeRunner
    # ffprobe = FFprobeRunner()
    # duration_sec = ffprobe.get_duration("path/to/input1.mp4") # Pass this to run

    print("\nRunning FFmpeg command...")
    ffmpeg.run(
        duration_sec=None, # Set if you have duration for progress
        progress_callback=lambda p: print(f"Progress: {p:.1f}%"), # Optional
        process_callback=lambda proc: print(f"FFmpeg PID: {proc.pid}"), # Optional
        check=True # Raise exception on non-zero exit code
    )
    print("FFmpeg command completed successfully.")

except FfmpegExecutableNotFoundError as e:
    print(f"Error: FFmpeg/FFprobe not found - {e}")
except FfmpegProcessError as e:
    print(f"Error during FFmpeg execution: {e}")
    print(f"Stderr:\n{e.stderr}") # Access detailed stderr
except CommandBuilderError as e:
    print(f"Error building FFmpeg command: {e}")
except FfmpegWrapperError as e:
    print(f"FFmpeg Wrapper Error: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")

```

### `just_ff.streams.MediaInfo`

Dataclasses representing the structure of `ffprobe -show_streams -show_format -print_format json` output.

-   `MediaInfo`: Contains `format` (`FormatInfo`) and `streams` (`List[StreamInfo]`).
-   `FormatInfo`: Contains information about the container format.
-   `StreamInfo`: Contains information about a single stream (video, audio, subtitle, etc.). Includes helper properties like `duration_sec`, `frame_rate_float`, `language`, `title`, `is_default`, `is_forced`.
-   Helper functions `safe_float`, `safe_int` for robust type conversion.

### `just_ff.exceptions`

Custom exception classes inheriting from `FfmpegWrapperError`:

-   `FfmpegExecutableNotFoundError`: FFmpeg/FFprobe not found.
-   `FfmpegProcessError`: Process exited with non-zero code. Includes command, exit code, stdout, stderr.
-   `FfprobeJsonError`: Failed to parse ffprobe output as JSON.
-   `CommandBuilderError`: Error during command building.

### `just_ff.process`

Low-level functions for running subprocesses:

-   `run_command(command, ...)`: Synchronously run a command, capture output, check exit code.
-   `run_ffmpeg_with_progress(command, duration_sec, progress_callback, process_callback, ...)`: Asynchronously run ffmpeg, parse stderr for progress, invoke callbacks.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request or open an Issue for bugs, feature requests, or improvements.

Before submitting a pull request, please ensure your code follows the project's style guidelines (PEP 8) and that all tests pass.

1.  Fork the repository.
2.  Create a new branch (`git checkout -b feature/your-feature`).
3.  Implement your feature or fix your bug.
4.  Write tests for your changes.
5.  Ensure all tests pass (`poetry run pytest`).
6.  Commit your changes (`git commit -m 'feat: Add your feature'`).
7.  Push to the branch (`git push origin feature/your-feature`).
8.  Open a Pull Request.

## Donate

You can support the development of this project via Monero:

`87QGCoHeYz74Ez22geY1QHerZqbN5J2z7JLNgyWijmrpCtDuw66kR7UQsWXWd6QCr3G86TBADcyFX5pNaqt7dpsEHE9HBJs`

[![imageban](https://i4.imageban.ru/thumbs/2025.04.15/566393a122f2a27b80defcbe9b074dc0.png)](https://imageban.ru/show/2025/04/15/566393a122f2a27b80defcbe9b074dc0/png)

I will also be happy to arrange any other way for you to transfer funds, please contact me.

## Contacts

*   Telegram: [@dimnissv](https://t.me/dimnissv)
*   Email: [dimnissv@yandex.kz](mailto:dimnissv@yandex.kz)

## License

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
