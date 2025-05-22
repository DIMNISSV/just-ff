# just-ff

A Python wrapper library for the FFmpeg and FFprobe command-line utilities.

## Introduction

`just-ff` provides a clean, Pythonic interface to interact with FFmpeg and FFprobe, making it easier to integrate media processing and analysis into your Python applications without directly managing subprocess calls and complex command-line arguments.

## Features

-   Run `ffprobe` to get detailed media information.
-   Build complex `ffmpeg` command-lines programmatically.
-   Run `ffmpeg` commands with real-time progress reporting.
-   Handle errors from FFmpeg/FFprobe processes.

## Installation

```bash
pip install git+https://github.com/DIMNISSV/just-ff
```

Make sure you have [FFmpeg](https://ffmpeg.org/download.html) installed and accessible in your system's PATH.

## Usage

```python
from just_ff import FFprobeRunner, FFmpegCommandBuilder

# --- Analyze a file ---
try:
    ffprobe = FFprobeRunner()
    media_info = ffprobe.get_media_info("input.mp4")
    print(f"Duration: {media_info.format.duration_sec:.2f} seconds")
    print(f"Video Codec: {media_info.streams[0].codec_name}")
except FileNotFoundError as e:
    print(f"Error: Input file not found - {e}")
except just_ff.FfmpegWrapperError as e:
    print(f"FFmpeg Wrapper Error: {e}")

# --- Build and run a conversion command ---
try:
    ffmpeg = FFmpegCommandBuilder(overwrite=True)
    ffmpeg.add_global_option("-loglevel", "info")
    ffmpeg.add_input("input.mp4", options=["-ss", "10"]) # Start from 10s
    ffmpeg.add_input("overlay.png", options=["-loop", "1"]) # Loop an image
    ffmpeg.add_filter_complex("[0:v][1:v] overlay=x='mod(t,W)':enable='gte(t,2)':shortest=0 [v_out]")
    ffmpeg.map_stream("[v_out]", "v:0") # Map filtered video to output video stream 0
    ffmpeg.map_stream("0:a:0", "a:0")   # Map audio from first input to output audio stream 0
    ffmpeg.set_codec("v:0", "libx264")
    ffmpeg.set_codec("a:0", "aac")
    ffmpeg.set_bitrate("a:0", "192k")
    ffmpeg.add_output("output.mp4")

    print("Generated Command:")
    print(ffmpeg.build())

    print("\nRunning FFmpeg...")
    # Example run with progress
    duration = ffprobe.get_duration("input.mp4") # Get duration for progress
    ffmpeg.run(
        duration_sec=duration,
        progress_callback=lambda p: print(f"Progress: {p:.1f}%"),
        check=True # Raise exception on failure
    )
    print("FFmpeg command finished.")

except just_ff.FfmpegExecutableNotFoundError as e:
    print(f"Error: FFmpeg/FFprobe not found - {e}")
except just_ff.FfmpegProcessError as e:
    print(f"Error during FFmpeg execution: {e}")
    # print(f"Stderr:\n{e.stderr}") # Access detailed stderr
except just_ff.FfmpegWrapperError as e:
    print(f"FFmpeg Wrapper Error: {e}")
except Exception as e:
    print(f"An unexpected error occurred: {e}")

```
