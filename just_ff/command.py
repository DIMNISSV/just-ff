# just_ff/command.py
import os
import typing
import shlex
from dataclasses import dataclass, field
import subprocess

from just_ff.process import run_ffmpeg_with_progress
from just_ff.exceptions import CommandBuilderError, FfmpegWrapperError, FfmpegExecutableNotFoundError, \
    FfmpegProcessError


@dataclass
class InputSpec:
    """Represents an input source for FFmpeg."""
    path: str
    options: typing.List[str] = field(default_factory=list)  # Options BEFORE -i
    # Map from unique stream ID (assigned externally) to local stream specifier (e.g., "v:0")
    # Not used directly by builder for mapping, but stored for potential external use/debugging
    stream_map: typing.Dict[str, str] = field(default_factory=dict, repr=False)
    input_index: int = -1  # Index assigned by the builder


@dataclass
class OutputSpec:
    """Represents an output target for FFmpeg."""
    path: str
    options: typing.List[str] = field(default_factory=list)  # General output file options
    # Maps and stream options are stored directly in _maps and _output_stream_opts
    # for easier handling of multi-output scenarios and overrides.
    output_index: int = -1  # Index assigned by the builder


class FFmpegCommandBuilder:
    """
    Builds FFmpeg command arguments in a structured way.

    Handles global options, multiple inputs/outputs, input/output options,
    stream-specific options (codecs, bitrates, metadata), mapping,
    filter_complex, and overriding map sources with filter labels.
    """

    def __init__(self, ffmpeg_path: str = "ffmpeg", overwrite: bool = True):
        """
        Initializes the command builder.

        Args:
            ffmpeg_path: Path to the ffmpeg executable.
            overwrite: If True, add the '-y' global option by default.
        """
        self.ffmpeg_path = ffmpeg_path
        self._global_opts: typing.List[typing.Tuple[str, typing.Optional[str]]] = []
        self._inputs: typing.List[InputSpec] = []
        self._outputs: typing.List[OutputSpec] = []
        self._filters: typing.List[str] = []
        self._filter_complex_script: typing.Optional[str] = None

        # --- Инициализируем словари как АТРИБУТЫ ЭКЗЕМПЛЯРА ---
        self._maps: typing.Dict[int, typing.Dict[str, str]] = {}  # <<< ДОБАВЛЕНО СЮДА
        self._output_stream_opts: typing.Dict[int, typing.Dict[str, typing.List[str]]] = {}  # <<< ДОБАВЛЕНО СЮДА

        if overwrite: self.add_global_option("-y")

    def reset(self) -> 'FFmpegCommandBuilder':
        """Clears all options, inputs, outputs, filters, and maps."""
        self._global_opts.clear()
        self._inputs.clear()
        self._outputs.clear()
        self._filters.clear()
        self._filter_complex_script = None
        self._maps.clear()
        self._output_stream_opts.clear()
        self.add_global_option("-y")  # Assuming default is True
        return self

    # --- Global Options ---
    def add_global_option(self, option: str, value: typing.Optional[str] = None) -> 'FFmpegCommandBuilder':
        """Adds a global option (before inputs)."""
        if not option.startswith('-'): raise CommandBuilderError(
            f"Invalid global option format: '{option}'. Must start with '-'.")
        # Simple check for flags:
        is_flag = value is None
        if is_flag and any(opt == option and val is None for opt, val in self._global_opts):
            print(f"Warning: Global flag '{option}' already added. Skipping.")
            return self
        self._global_opts.append((option, value))
        return self

    # --- Inputs ---
    def add_input(self, path: str, options: typing.Optional[typing.List[str]] = None,
                  stream_map: typing.Optional[typing.Dict[str, str]] = None) -> int:
        """
        Adds an input source.

        Args:
            path: Path to the input file.
            options: List of input options (strings) to place BEFORE this -i.
            stream_map: Optional dictionary mapping unique stream IDs (assigned externally)
                        to their local FFmpeg specifier within this input (e.g., {"sg0f0_v0": "v:0"}).
                        Stored in InputSpec but not used directly for -map generation here.

        Returns:
            The index of the added input (0-based).
        """
        if not path: raise CommandBuilderError("Input path cannot be empty.")
        input_index = len(self._inputs)
        spec = InputSpec(path=path, options=options or [], stream_map=stream_map or {}, input_index=input_index)
        self._inputs.append(spec)
        return input_index

    # --- Outputs ---
    def add_output(self, path: str, options: typing.Optional[typing.List[str]] = None) -> int:
        """
        Adds an output target.

        Args:
            path: Path for the output file.
            options: List of general output options (strings) for this output file.

        Returns:
            The index of the added output (0-based).
        """
        if not path: raise CommandBuilderError("Output path cannot be empty.")
        output_index = len(self._outputs)
        spec = OutputSpec(path=path, options=options or [], output_index=output_index)
        self._outputs.append(spec)
        # Инициализируем словари для этого нового выхода
        self._maps[output_index] = {}
        self._output_stream_opts[output_index] = {}
        return output_index

    # --- Mapping ---
    def map_stream(self, source_specifier: str, output_specifier: str, output_index: int = 0) -> 'FFmpegCommandBuilder':
        """
        Declares an intent to map a source stream to a specific output stream specifier
        for a particular output file.

        Args:
            source_specifier: The source (e.g., "0:a:1", "[filtered_audio]").
            output_specifier: The target output stream identifier (e.g., "v:0", "a:1").
            output_index: The index of the output file this map belongs to (default 0).

        Returns:
            self
        """
        if output_index >= len(self._outputs): raise CommandBuilderError(
            f"Output index {output_index} out of range ({len(self._outputs)} outputs defined).")
        if not output_specifier or ':' not in output_specifier: raise CommandBuilderError(
            f"Invalid output_specifier format: '{output_specifier}'. Expected 'v:0', 'a:1', etc.")
        # Ensure output_index keys exist (should be done by add_output)
        self._maps.setdefault(output_index, {})
        # Store the mapping: {output_specifier: source_specifier} for this output_index
        if output_specifier in self._maps[output_index]:
            print(
                f"Warning: Overwriting map for output '{output_index}:{output_specifier}'. Previous source: '{self._maps[output_index][output_specifier]}', New source: '{source_specifier}'")
        self._maps[output_index][output_specifier] = source_specifier
        return self

    # --- Filter Complex ---
    def add_filter_complex(self, filter_graph: str) -> 'FFmpegCommandBuilder':
        """Adds a filtergraph string to the command."""
        if self._filter_complex_script: raise CommandBuilderError(
            "Cannot use both add_filter_complex and add_filter_complex_script.")
        self._filters.append(filter_graph)
        return self

    def add_filter_complex_script(self, script_path: str) -> 'FFmpegCommandBuilder':
        """Specifies a file containing the filter_complex graph."""
        if self._filters: raise CommandBuilderError("Cannot use both add_filter_complex and add_filter_complex_script.")
        if not os.path.exists(script_path): print(f"Warning: Filter complex script file not found: {script_path}")
        self._filter_complex_script = script_path
        return self

    # --- Output Stream Specific Options ---
    def _add_stream_option(self, output_index: int, output_specifier: str, option: str, value: typing.Optional[str]):
        """Internal helper to add options to a specific output stream for a given output file."""
        if output_index >= len(self._outputs): raise CommandBuilderError(
            f"Output index {output_index} out of range ({len(self._outputs)} outputs defined).")
        if output_specifier != 'g' and (not output_specifier or ':' not in output_specifier):
            raise CommandBuilderError(
                f"Invalid output_specifier format: '{output_specifier}'. Expected 'v:0', 'a:1', etc.")

        # Ensure output_index and output_specifier keys exist
        self._output_stream_opts.setdefault(output_index, {})
        self._output_stream_opts[output_index].setdefault(output_specifier, [])

        # Add the option and value (if not None)
        self._output_stream_opts[output_index][output_specifier].append(option)
        if value is not None: self._output_stream_opts[output_index][output_specifier].append(str(value))

    def set_codec(self, output_specifier: str, codec: str, output_index: int = 0) -> 'FFmpegCommandBuilder':
        """Sets the codec for a specific output stream."""
        option = f"-c:{output_specifier}"
        self._add_stream_option(output_index, output_specifier, option, codec)
        return self

    def set_bitrate(self, output_specifier: str, bitrate: str, output_index: int = 0) -> 'FFmpegCommandBuilder':
        """Sets the bitrate for a specific output stream (e.g., '5000k', '192k', '0')."""
        if bitrate != "0" and not bitrate.endswith('k') and not bitrate.endswith('M'):
            print(f"Warning: Bitrate '{bitrate}' for {output_specifier} might require units (e.g., 'k' or 'M').")
        option = f"-b:{output_specifier}"
        self._add_stream_option(output_index, output_specifier, option, bitrate)
        return self

    def set_metadata(self, stream_specifier_metadata: str, key: str, value: str,
                     output_index: int = 0) -> 'FFmpegCommandBuilder':
        """Sets a metadata key-value pair for a specific output stream."""
        option = f"-metadata:{stream_specifier_metadata}"
        metadata_str = f"{key}={value}"
        self._add_stream_option(output_index, stream_specifier_metadata, option, metadata_str)
        return self

    def add_output_option(self, option: str, value: typing.Optional[str] = None,
                          stream_specifier: typing.Optional[str] = None,
                          output_index: int = 0) -> 'FFmpegCommandBuilder':
        """Adds a generic option for a specific output file or stream."""
        if output_index >= len(self._outputs): raise CommandBuilderError(
            f"Output index {output_index} out of range ({len(self._outputs)} outputs defined).")

        if stream_specifier:
            # Add as a stream-specific option
            option_key = f"{option}:{stream_specifier}" if not option.endswith(':') else option + stream_specifier
            self._add_stream_option(output_index, stream_specifier, option_key, value)
        else:
            # Add as a general output file option (goes into OutputSpec.options)
            output = self._outputs[output_index]
            output.options.append(option)
            if value is not None: output.options.append(str(value))
        return self

    def add_parsed_options(self, options_str: str, output_index: int = 0,
                           stream_specifier: typing.Optional[str] = None) -> 'FFmpegCommandBuilder':
        """Parses a string of options using shlex and adds them to a specific output or output stream."""
        if not options_str: return self
        try:
            opts_list = shlex.split(options_str)
            opt_key = None
            parsed_opts = []
            for part in opts_list:
                if part.startswith('-'):
                    if opt_key: parsed_opts.append((opt_key, None))
                    opt_key = part
                else:
                    if opt_key:
                        parsed_opts.append((opt_key, part))
                    else:
                        print(f"Warning: Ignoring option part without preceding key: {part}")
                    opt_key = None
            if opt_key: parsed_opts.append((opt_key, None))

            for opt, val in parsed_opts:
                # Добавляем через add_output_option, чтобы использовать существующую логику
                self.add_output_option(opt, val, stream_specifier=stream_specifier, output_index=output_index)

            return self
        except Exception as e:
            raise CommandBuilderError(f"Failed to parse options string '{options_str}': {e}") from e

    # --- Building the Command ---
    def _build_input_args(self) -> typing.List[str]:
        args = []
        for inp in self._inputs:
            args.extend(inp.options)
            args.extend(["-i", inp.path])
        return args

    def _build_filter_args(self) -> typing.List[str]:
        args = []
        if self._filters:
            args.extend(["-filter_complex", ";".join(self._filters)])
        elif self._filter_complex_script:
            args.extend(["-filter_complex_script", self._filter_complex_script])
        return args

    def _build_output_args(self) -> typing.List[str]:
        """Builds the output arguments part of the command."""
        args = []
        # Iterate through outputs in the order they were added
        for output_index, output in enumerate(self._outputs):
            # Ensure this output index has map and stream_opts dictionaries
            maps_for_output = self._maps.get(output_index, {})
            stream_opts_for_output = self._output_stream_opts.get(output_index, {})

            # 1. Add maps for this output
            # Maps should be added using -map source -map source ...
            # The source can be an input specifier or a filter label
            # Order might matter for some formats, so iterate through output_specifiers v:0, a:0, s:0 etc.
            # based on the order they were mapped.
            # The _maps[output_index] dict stores the mapping per output_specifier.
            # Need to preserve the order in which output_specifiers were mapped for this output.
            # The _preliminary_maps structure in previous versions implicitly stored order,
            # but now _maps is just a dict.
            # Let's rebuild the order based on the keys added to _maps[output_index]
            # Or enforce mapping v:0, a:0, a:1, s:0 order? Yes, that's safer.

            # Get the list of mapped output_specifiers for this output, ordered by type and index
            ordered_output_specs = sorted(maps_for_output.keys(), key=lambda spec: (spec[0], int(spec.split(':')[1])))

            for output_spec in ordered_output_specs:
                source_spec = maps_for_output[output_spec]
                args.extend(["-map", source_spec])  # Add the map command

            # 2. Add stream-specific options for this output
            # Iterate through output_specifiers for this output, ordered by type and index
            for output_spec in ordered_output_specs:
                if output_spec in stream_opts_for_output:
                    # Add the list of options for this stream
                    args.extend(stream_opts_for_output[output_spec])

            # 3. Add general output options for this output
            args.extend(output.options)

            # 4. Add the output path
            args.append(output.path)

        return args

    def build_list(self) -> typing.List[str]:
        if not self._outputs: raise CommandBuilderError("Cannot build command: No outputs defined.")
        if not self._inputs and not self._filters and not self._filter_complex_script:
            print("Warning: Building command with no inputs or filters defined.")

        command = [self.ffmpeg_path]
        # Add global options
        for opt, val in self._global_opts:
            command.append(opt)
            if val is not None: command.append(val)
        # Add inputs
        command.extend(self._build_input_args())
        # Add filters
        command.extend(self._build_filter_args())
        # Add outputs
        command.extend(self._build_output_args())

        # Convert all args to strings before returning
        return [str(arg) for arg in command]

    def build(self) -> str:
        args = self.build_list()
        # Use shlex.quote for arguments containing spaces or special chars
        # This is important if passing the command string to a shell
        # However, subprocess.Popen(command_list) is generally safer as it avoids shell parsing
        # If the command string is for display or manual copying, simple join might be enough
        # Let's provide the shlex.quote version for robustness if needed as a string
        return " ".join(shlex.quote(arg) for arg in args)

    # --- Running the Command ---
    def run(self,
            duration_sec: typing.Optional[float] = None,
            progress_callback: typing.Optional[typing.Callable[[float], None]] = None,
            process_callback: typing.Optional[typing.Callable[[subprocess.Popen], None]] = None,
            check: bool = True
            ) -> bool:
        try:
            command_list = self.build_list()
            return run_ffmpeg_with_progress(
                command=command_list,  # Pass as list
                duration_sec=duration_sec,
                progress_callback=progress_callback,
                process_callback=process_callback,
                check=check
            )
        except (CommandBuilderError, FfmpegExecutableNotFoundError, FfmpegProcessError, TypeError,
                FfmpegWrapperError) as e:
            raise e
        except Exception as e:
            raise FfmpegWrapperError(f"Unexpected error during command build or run: {e}") from e
