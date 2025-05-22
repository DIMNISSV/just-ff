# just-ff

A Python wrapper library for the FFmpeg and FFprobe command-line utilities.

![GitHub Tag](https://img.shields.io/github/v/tag/DIMNISSV/just-ff)
![License](https://img.shields.io/github/license/DIMNISSV/just-ff) 
![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)
![ffmpeg Version](https://img.shields.io/badge/ffmpeg-7.0%2B-darkgreen.svg)

## Introduction

`just-ff` provides a clean, Pythonic interface to interact with FFmpeg and FFprobe. It simplifies media processing and analysis in Python applications by abstracting away direct subprocess management and complex command-line argument construction. The library focuses on robust command building, process execution with progress reporting, structured output parsing, and sequential job queuing.

## Features

-   **FFprobe Integration (`FFprobeRunner`):**
    -   Retrieve detailed media information (format, streams, codecs, duration, etc.).
    -   Parsed output into convenient dataclasses (`MediaInfo`, `StreamInfo`, `FormatInfo`).
-   **FFmpeg Command Building (`FFmpegCommandBuilder`):**
    -   Programmatically construct complex FFmpeg commands with a fluent interface.
    -   Manage global options, multiple inputs/outputs, input/output specific options.
    -   Handle stream mapping (including from filter complex outputs).
    -   Set codecs, bitrates, metadata, and custom options for output streams.
    -   Define complex filter graphs.
-   **FFmpeg Execution:**
    -   Run FFmpeg commands with real-time percentage progress reporting (via `run_ffmpeg_with_progress` or `FFmpegCommandBuilder.run()`).
    -   Capture process output and handle FFmpeg errors gracefully.
-   **Job Queuing (`FFmpegQueueRunner`):**
    -   Create and manage a queue of FFmpeg jobs.
    -   Run jobs sequentially with callbacks for job/queue start, progress, and completion.
    -   Option to stop queue on error or continue processing.
    -   Cancel individual jobs or the entire queue.
-   **Custom Exceptions:** Specific exceptions for common errors (`FfmpegExecutableNotFoundError`, `FfmpegProcessError`, `FfprobeJsonError`, `CommandBuilderError`).
-   **Minimal Dependencies:** Relies primarily on Python's standard library.

## Installation

You can install `just-ff` in several ways:

### From GitHub

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

### Prerequisites

**FFMPEG:**

Make sure you have [FFMPEG](https://ffmpeg.org/download.html) installed and accessible in your system's PATH.
`just-ff` is a wrapper, it does **not** include the FFmpeg binaries.

**Python:**

Make sure you have [Python](https://www.python.org/downloads/) installed and accessible in your system's PATH.

## Quick Start

### 1. Probing Media Files

```python
from just_ff import FFprobeRunner, FfmpegWrapperError, FileNotFoundError

ffprobe = FFprobeRunner() # Assumes ffprobe is in PATH

try:
    media_info = ffprobe.get_media_info("input.mp4")

    print(f"File: {media_info.format.filename}")
    print(f"Duration: {media_info.format.duration_sec:.2f}s")
    for stream in media_info.streams:
        print(f"  Stream #{stream.index} ({stream.codec_type}): {stream.codec_name}")
        if stream.codec_type == 'video':
            print(f"    Res: {stream.width}x{stream.height}, FPS: {stream.frame_rate_float:.2f}")
        elif stream.codec_type == 'audio':
            print(f"    Sample Rate: {stream.sample_rate} Hz, Channels: {stream.channels}")

except FileNotFoundError:
    print("Error: Input file not found.")
except FfmpegWrapperError as e:
    print(f"FFprobe Error: {e}")
```

### 2. Building and Running an FFmpeg Command

```python
from just_ff import FFmpegCommandBuilder, FFprobeRunner # FFprobeRunner for duration
from just_ff.exceptions import FfmpegProcessError

# Get input duration for progress reporting (optional but recommended)
ffprobe = FFprobeRunner()
input_duration = ffprobe.get_duration("input.mp4")

ffmpeg = FFmpegCommandBuilder(overwrite=True) # -y global option by default

# Configure command
input_idx = ffmpeg.add_input("input.mp4", options=["-ss", "10"]) # Start from 10s
output_idx = ffmpeg.add_output("output_recode.mkv")

ffmpeg.map_stream(f"{input_idx}:v:0", "v:0", output_index=output_idx)
ffmpeg.set_codec("v:0", "libx265", output_index=output_idx)
ffmpeg.add_output_option("-preset", "medium", stream_specifier="v:0", output_index=output_idx)
ffmpeg.add_output_option("-crf", "23", stream_specifier="v:0", output_index=output_idx)

ffmpeg.map_stream(f"{input_idx}:a:0", "a:0", output_index=output_idx)
ffmpeg.set_codec("a:0", "aac", output_index=output_idx)
ffmpeg.set_bitrate("a:0", "128k", output_index=output_idx)

print("Generated command:", ffmpeg.build())

# Run the command
try:
    ffmpeg.run(
        duration_sec=input_duration,
        progress_callback=lambda p: print(f"Progress: {p:.1f}%", end='\r'),
        process_callback=lambda proc: print(f"FFmpeg PID: {proc.pid}"),
        check=True # Raise FfmpegProcessError on failure
    )
    print("\nFFmpeg command completed successfully.")
except FfmpegProcessError as e:
    print(f"\nError during FFmpeg execution (Code: {e.exit_code}):")
    print(f"Command: {' '.join(e.command)}")
    print(f"Stderr: {e.stderr}")
except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")
```

### 3. Using the FFmpeg Job Queue

```python
from just_ff import FFmpegCommandBuilder, FFmpegQueueRunner, FFmpegJob

# --- Define Callbacks (optional) ---
def my_job_start(idx, job: FFmpegJob):
    print(f"[Q] Job {job.job_id or idx} started.")

def my_job_progress(idx, job: FFmpegJob, percent: float):
    print(f"\r[Q] Job {job.job_id or idx}: {percent:.1f}%", end="")
    if percent == 100.0: print()

def my_job_complete(idx, job: FFmpegJob):
    print(f"[Q] Job {job.job_id or idx} completed with status: {job.status}")
    if job.status == "failed":
        print(f"  Error: {job.error_message}")

def my_queue_complete(runner: FFmpegQueueRunner, processed_jobs: list[FFmpegJob]):
    print(f"[Q] Queue finished. Processed {len(processed_jobs)} jobs.")

# --- Initialize Queue Runner ---
queue_runner = FFmpegQueueRunner(
    on_job_start=my_job_start,
    on_job_progress=my_job_progress,
    on_job_complete=my_job_complete,
    on_queue_complete=my_queue_complete
)

# --- Create and Add Jobs ---
# Job 1: Convert video to a different format
builder1 = FFmpegCommandBuilder(overwrite=True)
builder1.add_input("video.mp4").add_output("video_converted.webm")
builder1.map_stream("0:v", "v:0").set_codec("v:0", "libvpx-vp9")
builder1.map_stream("0:a", "a:0").set_codec("a:0", "libopus")
# duration1 = ffprobe.get_duration("video.mp4") # Get duration for progress
queue_runner.add_job(builder1, duration_sec=None, job_id="ConvertMP4toWebM")

# Job 2: Extract audio
builder2 = FFmpegCommandBuilder(overwrite=True)
builder2.add_input("another_video.mkv").add_output("audio_extract.aac")
builder2.map_stream("0:a:0", "a:0").set_codec("a:0", "aac").set_bitrate("a:0", "192k")
# duration2 = ffprobe.get_duration("another_video.mkv")
queue_runner.add_job(builder2, duration_sec=None, job_id="ExtractAudio")

# --- Run the Queue ---
print(f"Starting queue with {queue_runner.pending_job_count} jobs...")
# This is a blocking call. For GUI apps, run this in a separate thread.
processed_results = queue_runner.run_queue(stop_on_error=False)

# `processed_results` contains a list of FFmpegJob objects with their final status.
for job_result in processed_results:
    print(f"Final status for {job_result.job_id}: {job_result.status}")
```

## Documentation

### Core Components

*   **`just_ff.probe.FFprobeRunner`**:
    *   `get_media_info(file_path: str) -> MediaInfo`: Returns comprehensive format and stream information.
    *   `get_duration(file_path: str) -> Optional[float]`: Gets the media duration in seconds.
    *   `run_ffprobe(args: List[str]) -> Dict`: Runs a custom ffprobe command and returns parsed JSON.
*   **`just_ff.command.FFmpegCommandBuilder`**:
    *   `add_global_option(option: str, value: Optional[str] = None)`
    *   `add_input(path: str, options: Optional[List[str]] = None, stream_map: Optional[Dict[str, str]] = None) -> int`
    *   `add_output(path: str, options: Optional[List[str]] = None) -> int`
    *   `map_stream(source_specifier: str, output_specifier: str, output_index: int = 0)`
    *   `add_filter_complex(filter_graph: str)` / `add_filter_complex_script(script_path: str)`
    *   `set_codec(output_specifier: str, codec: str, output_index: int = 0)`
    *   `set_bitrate(output_specifier: str, bitrate: str, output_index: int = 0)`
    *   `set_metadata(stream_specifier_metadata: str, key: str, value: str, output_index: int = 0)`
    *   `add_output_option(option: str, value: Optional[str] = None, stream_specifier: Optional[str] = None, output_index: int = 0)`
    *   `add_parsed_options(options_str: str, output_index: int = 0, stream_specifier: Optional[str] = None)`
    *   `build_list() -> List[str]`: Returns the command as a list of arguments.
    *   `build() -> str`: Returns the command as a shell-escaped string.
    *   `run(...) -> bool`: Executes the built command with progress reporting.
    *   `reset()`: Clears all settings in the builder.
*   **`just_ff.queue.FFmpegQueueRunner`**:
    *   `add_job(builder: FFmpegCommandBuilder, duration_sec: Optional[float], job_id: Optional[str], context: Any) -> FFmpegJob`
    *   `run_queue(stop_on_error: bool = True) -> List[FFmpegJob]`
    *   `cancel_current_job() -> bool`
    *   `cancel_queue()`
    *   `clear_pending_jobs() -> int`
    *   Properties: `is_running`, `active_job`, `pending_job_count`
    *   Callback parameters for `on_job_start`, `on_job_progress`, `on_job_process_created`, `on_job_complete`, `on_queue_start`, `on_queue_complete`.
*   **`just_ff.queue.FFmpegJob` (Dataclass)**: Represents a job in the queue, holding the builder, parameters, and status.

### Data Structures (`just_ff.streams`)

*   **`MediaInfo`**: Container for `format` (`FormatInfo`) and `streams` (`List[StreamInfo]`).
*   **`FormatInfo`**: Information about the media container format.
*   **`StreamInfo`**: Information about a single media stream (video, audio, subtitle). Includes helper properties like `duration_sec`, `frame_rate_float`, `language`, `title`, `is_default`, `is_forced`.
*   Helper functions `safe_float()`, `safe_int()` for robust type conversion.

### Exceptions (`just_ff.exceptions`)

Custom exceptions inherit from `FfmpegWrapperError`:

*   `FfmpegExecutableNotFoundError`: FFmpeg/FFprobe executable not found.
*   `FfmpegProcessError`: FFmpeg/FFprobe process exited with a non-zero code. Includes command, exit code, stdout, and stderr.
*   `FfprobeJsonError`: Failed to parse ffprobe output as JSON.
*   `CommandBuilderError`: Error during FFmpeg command construction.

### Low-level Process Utilities (`just_ff.process`)

*   `run_command(command: List[str], ...)`: Synchronously runs an external command.
*   `run_ffmpeg_with_progress(command: List[str], duration_sec: Optional[float], ...)`: Runs FFmpeg, parsing stderr for progress.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request or open an Issue for bugs, feature requests, or improvements.

Before submitting a pull request, please ensure your code:
1.  Adheres to PEP 8 style guidelines.
2.  Includes tests for new features or bug fixes.
3.  All existing and new tests pass (`poetry run pytest`).

**Development Setup:**

```bash
git clone https://github.com/DIMNISSV/just-ff.git
cd just-ff
poetry install # Installs dependencies, including dev dependencies like pytest
```

**Workflow:**

1.  Create a new branch (`git checkout -b feature/your-awesome-feature`).
2.  Implement your changes and write tests.
3.  Run tests: `poetry run pytest`.
4.  Commit your changes (`git commit -m 'feat: Add awesome feature'`).
5.  Push to the branch (`git push origin feature/your-awesome-feature`).
6.  Open a Pull Request on GitHub.

## Donate

If you find this library useful and wish to support its development, you can contribute via Monero:

`87QGCoHeYz74Ez22geY1QHerZqbN5J2z7JLNgyWijmrpCtDuw66kR7UQsWXWd6QCr3G86TBADcyFX5pNaqt7dpsEHE9HBJs`

[![Monero QR Code](https://i4.imageban.ru/thumbs/2025.04.15/566393a122f2a27b80defcbe9b074dc0.png)](https://imageban.ru/show/2025/04/15/566393a122f2a27b80defcbe9b074dc0/png)

Alternative ways to support the project can be arranged; please feel free to contact me.

## Contacts

*   **Telegram:** [@dimnissv](https://t.me/dimnissv)
*   **Email:** [dimnissv@yandex.kz](mailto:dimnissv@yandex.kz)

## License

This project is licensed under the MIT License. See the [LICENSE.md](LICENSE.md) file for details.
