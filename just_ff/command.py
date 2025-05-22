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
        self._maps: typing.Dict[int, typing.Dict[str, str]] = {}
        self._output_stream_opts: typing.Dict[int, typing.Dict[str, typing.List[str]]] = {}

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
        # Re-add default overwrite option if it was initially set
        # To do this properly, we'd need to store the initial overwrite state.
        # For now, assuming if reset is called, user might want the default overwrite.
        # A better approach might be to not auto-add -y on reset unless overwrite was true.
        if ("-y", None) in self._global_opts or any(opt == "-y" for opt, _ in self._global_opts):
            pass  # If -y was added due to overwrite=True, it's already in global_opts for add_global_option to handle
        else:  # if overwrite was false initially, or -y was manually removed.
            # The original code does self.add_global_option("-y")
            # This assumes overwrite=True is the default for reset.
            # Let's keep it consistent with the original reset logic.
            self.add_global_option("-y")
        return self

    # --- Global Options ---
    def add_global_option(self, option: str, value: typing.Optional[str] = None) -> 'FFmpegCommandBuilder':
        """Adds a global option (before inputs)."""
        if not option.startswith('-'): raise CommandBuilderError(
            f"Invalid global option format: '{option}'. Must start with '-'.")
        is_flag = value is None
        if is_flag and any(opt == option and val is None for opt, val in self._global_opts):
            # Warning for duplicate flags can be noisy, let's make it conditional or remove.
            # For example, reset() calls add_global_option("-y").
            # print(f"Warning: Global flag '{option}' already added. Skipping.")
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
        self._maps.setdefault(output_index, {})
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
        if output_specifier != 'g' and (
                not output_specifier or (':' not in output_specifier and not output_specifier.isalpha())):
            # Allow single char specifiers like 'v', 'a', 's' if FFmpeg supports them in context (e.g. -disposition:s)
            # But generally, 'v:0', 'a:1' is safer.
            # The check `':' not in output_specifier` handles basic cases.
            # Adding `not output_specifier.isalpha()` to make sure if it's just 's', it's single char.
            # This check could be more refined based on FFmpeg specifier rules.
            if not (len(output_specifier) == 1 and output_specifier.isalpha()):  # Allow 'v', 'a', 's'
                if ':' not in output_specifier:
                    raise CommandBuilderError(
                        f"Invalid output_specifier format: '{output_specifier}'. Expected 'v:0', 'a:1', 's', etc.")

        self._output_stream_opts.setdefault(output_index, {})
        self._output_stream_opts[output_index].setdefault(output_specifier, [])

        self._output_stream_opts[output_index][output_specifier].append(option)
        if value is not None: self._output_stream_opts[output_index][output_specifier].append(str(value))

    def set_codec(self, output_specifier: str, codec: str, output_index: int = 0) -> 'FFmpegCommandBuilder':
        """Sets the codec for a specific output stream."""
        option = f"-c:{output_specifier}"
        self._add_stream_option(output_index, output_specifier, option, codec)
        return self

    def set_bitrate(self, output_specifier: str, bitrate: str, output_index: int = 0) -> 'FFmpegCommandBuilder':
        """Sets the bitrate for a specific output stream (e.g., '5000k', '192k', '0')."""
        if bitrate != "0" and not bitrate.endswith('k') and not bitrate.endswith('M') and not bitrate.endswith('G'):
            try:  # Check if it's a number that might imply bps
                int(bitrate)
            except ValueError:  # Not a plain number, and no k/M/G suffix
                print(
                    f"Warning: Bitrate '{bitrate}' for {output_specifier} might require units (e.g., 'k', 'M', or 'G').")
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
            option_key = f"{option}:{stream_specifier}" if not option.endswith(':') else option + stream_specifier
            self._add_stream_option(output_index, stream_specifier, option_key, value)
        else:
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
                        opt_key = None  # Reset after consuming value
                    else:
                        # This case might be an error or a multi-part value for a previous option.
                        # Shlex usually handles quoted strings as single parts.
                        # For simplicity, we assume values always follow keys.
                        print(f"Warning: Ignoring option part without preceding key: {part} in '{options_str}'")
            if opt_key: parsed_opts.append((opt_key, None))  # Add last key if it was a flag

            for opt, val in parsed_opts:
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

        def stream_specifier_sort_key(spec: str) -> tuple:
            original_spec = spec

            if spec == 'g':
                return 5, 0, original_spec

            effective_type_char = ''
            effective_index = -1  # Default for non-indexed or unparsed

            parts = spec.split(':', 1)
            first_part = parts[0]

            if first_part == 's' and len(parts) > 1 and parts[1] and ':' in parts[1]:
                # Metadata key like 's:v:0' or 's:a:custom'
                sub_spec_parts = parts[1].split(':', 1)
                effective_type_char = sub_spec_parts[0]
                if len(sub_spec_parts) > 1 and sub_spec_parts[1].isdigit():
                    effective_index = int(sub_spec_parts[1])
            elif first_part.isalpha():  # Standard specifier like 'v', 'a', or a label
                effective_type_char = first_part
                if len(parts) > 1 and parts[1].isdigit():
                    effective_index = int(parts[1])
            else:  # Fallback for unusual specifiers, sort them later
                return 6, -1, original_spec

            type_priority_map = {
                'v': 0, 'V': 0,
                'a': 1, 'A': 1,
                's': 2, 'S': 2,
                'd': 3, 'D': 3,
                't': 4, 'T': 4
            }
            group = type_priority_map.get(effective_type_char, 6)
            return group, effective_index, original_spec

        for output_index, output in enumerate(self._outputs):
            maps_for_output = self._maps.get(output_index, {})
            stream_opts_for_output = self._output_stream_opts.get(output_index, {})

            # 1. Add maps for this output
            # Keys of maps_for_output are output stream specifiers like "v:0", "a:1"
            ordered_map_keys = sorted(maps_for_output.keys(), key=stream_specifier_sort_key)
            for map_key_spec in ordered_map_keys:
                source_spec = maps_for_output[map_key_spec]
                args.extend(["-map", source_spec])

            # 2. Add stream-specific options for this output (FIXED PART)
            # Iterate over keys from stream_opts_for_output, not maps_for_output
            ordered_stream_option_keys = sorted(stream_opts_for_output.keys(), key=stream_specifier_sort_key)
            for stream_opt_key in ordered_stream_option_keys:
                args.extend(stream_opts_for_output[stream_opt_key])

            # 3. Add general output options for this output (from OutputSpec.options)
            args.extend(output.options)

            # 4. Add the output path
            args.append(output.path)
        return args

    def build_list(self) -> typing.List[str]:
        if not self._outputs: raise CommandBuilderError("Cannot build command: No outputs defined.")
        if not self._inputs and not self._filters and not self._filter_complex_script:
            # Allow commands with only -lavfi inputs via filter_complex generating source
            # This warning might be too strict if filter_complex provides the source.
            # print("Warning: Building command with no -i inputs defined. Ensure filter_complex provides a source if needed.")
            pass

        command = [self.ffmpeg_path]
        for opt, val in self._global_opts:
            command.append(opt)
            if val is not None: command.append(val)

        command.extend(self._build_input_args())
        command.extend(self._build_filter_args())
        command.extend(self._build_output_args())

        return [str(arg) for arg in command]

    def build(self) -> str:
        args = self.build_list()
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
                command=command_list,
                duration_sec=duration_sec,
                progress_callback=progress_callback,
                process_callback=process_callback,
                check=check
            )
        except (CommandBuilderError, FfmpegExecutableNotFoundError, FfmpegProcessError, TypeError,
                FfmpegWrapperError) as e:  # Explicitly catch known errors
            raise e
        except Exception as e:  # Catch any other unexpected error
            raise FfmpegWrapperError(f"Unexpected error during command build or run: {e}") from e