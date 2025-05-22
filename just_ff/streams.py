# just_ff/streams.py
import typing
from dataclasses import dataclass, field, asdict, fields  # Импортируем fields для интроспекции


# --- Helper Functions ---
def safe_float(value: typing.Any, default: typing.Optional[float] = None) -> typing.Optional[float]:
    """Safely converts a value to float, returning default on failure."""
    if value is None: return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: typing.Any, default: typing.Optional[int] = None) -> typing.Optional[int]:
    """Safely converts a value to int, returning default on failure."""
    if value is None: return default
    try:
        return int(float(value))  # Handle potential float strings like "10.0"
    except (ValueError, TypeError):
        return default


# --- Dataclasses for Media Information ---

@dataclass
class StreamInfo:
    """Represents information about a single media stream."""
    index: typing.Optional[int] = None
    codec_name: typing.Optional[str] = None
    codec_long_name: typing.Optional[str] = None
    codec_type: typing.Optional[str] = None
    codec_tag_string: typing.Optional[str] = None
    codec_tag: typing.Optional[str] = None
    time_base: typing.Optional[str] = None
    start_pts: typing.Optional[int] = None
    start_time: typing.Optional[float] = None
    duration_ts: typing.Optional[int] = None
    duration: typing.Optional[float] = None
    bit_rate: typing.Optional[int] = None
    bits_per_raw_sample: typing.Optional[int] = None
    bits_per_sample: typing.Optional[int] = None
    disposition: typing.Dict[str, int] = field(default_factory=dict)
    tags: typing.Dict[str, str] = field(default_factory=dict)
    width: typing.Optional[int] = None
    height: typing.Optional[int] = None
    coded_width: typing.Optional[int] = None
    coded_height: typing.Optional[int] = None
    has_b_frames: typing.Optional[int] = None
    sample_aspect_ratio: typing.Optional[str] = None
    display_aspect_ratio: typing.Optional[str] = None
    pix_fmt: typing.Optional[str] = None
    level: typing.Optional[int] = None
    color_range: typing.Optional[str] = None
    color_space: typing.Optional[str] = None
    color_transfer: typing.Optional[str] = None
    color_primaries: typing.Optional[str] = None
    chroma_location: typing.Optional[str] = None
    field_order: typing.Optional[str] = None
    r_frame_rate: typing.Optional[str] = None
    avg_frame_rate: typing.Optional[str] = None
    sample_fmt: typing.Optional[str] = None
    sample_rate: typing.Optional[int] = None
    channels: typing.Optional[int] = None
    channel_layout: typing.Optional[str] = None
    initial_padding: typing.Optional[int] = None

    # Field assigned externally (e.g., by JustConverter's logic), not from ffprobe dict directly
    unique_id: str = field(default="", init=False, repr=False)

    # --- Calculated / Helper Properties ---
    @property
    def is_default(self) -> bool:
        return bool(self.disposition.get("default"))

    @property
    def is_forced(self) -> bool:
        return bool(self.disposition.get("forced"))

    @property
    def language(self) -> typing.Optional[str]:
        return self.tags.get("language")

    @property
    def title(self) -> typing.Optional[str]:
        return self.tags.get("title")

    @property
    def duration_sec(self) -> typing.Optional[float]:
        if self.duration is not None and self.duration > 0: return self.duration
        if self.duration_ts is not None and self.time_base:
            try:
                num, den = map(float, self.time_base.split('/'))
                return self.duration_ts * (num / den) if den != 0 else None
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        return None

    @property
    def frame_rate_float(self) -> typing.Optional[float]:
        rate_str = self.r_frame_rate or self.avg_frame_rate
        if not rate_str: return None
        try:
            if '/' in rate_str:
                num, den = map(float, rate_str.split('/'))
                return num / den if den != 0 else None
            else:
                return float(rate_str)
        except (ValueError, TypeError, ZeroDivisionError):
            return None

    @classmethod
    def from_dict(cls, data: dict) -> 'StreamInfo':
        """Creates StreamInfo from a dictionary (e.g., ffprobe stream output)."""
        # Filter data keys to match dataclass fields ignoring 'unique_id' as it's init=False
        # Use fields(cls) to get dataclass fields
        known_fields = {f.name for f in fields(cls) if f.init}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        # Perform type conversions on the filtered data
        if 'index' in filtered_data: filtered_data['index'] = safe_int(filtered_data['index'])
        if 'start_pts' in filtered_data: filtered_data['start_pts'] = safe_int(filtered_data['start_pts'])
        if 'start_time' in filtered_data: filtered_data['start_time'] = safe_float(filtered_data['start_time'])
        if 'duration_ts' in filtered_data: filtered_data['duration_ts'] = safe_int(filtered_data['duration_ts'])
        if 'duration' in filtered_data: filtered_data['duration'] = safe_float(filtered_data['duration'])
        if 'bit_rate' in filtered_data: filtered_data['bit_rate'] = safe_int(filtered_data['bit_rate'])
        if 'bits_per_raw_sample' in filtered_data: filtered_data['bits_per_raw_sample'] = safe_int(
            filtered_data['bits_per_raw_sample'])
        if 'bits_per_sample' in filtered_data: filtered_data['bits_per_sample'] = safe_int(
            filtered_data['bits_per_sample'])
        if 'width' in filtered_data: filtered_data['width'] = safe_int(filtered_data['width'])
        if 'height' in filtered_data: filtered_data['height'] = safe_int(filtered_data['height'])
        if 'coded_width' in filtered_data: filtered_data['coded_width'] = safe_int(filtered_data['coded_width'])
        if 'coded_height' in filtered_data: filtered_data['coded_height'] = safe_int(filtered_data['coded_height'])
        if 'has_b_frames' in filtered_data: filtered_data['has_b_frames'] = safe_int(filtered_data['has_b_frames'])
        if 'level' in filtered_data: filtered_data['level'] = safe_int(filtered_data['level'])
        if 'sample_rate' in filtered_data: filtered_data['sample_rate'] = safe_int(filtered_data['sample_rate'])
        if 'channels' in filtered_data: filtered_data['channels'] = safe_int(filtered_data['channels'])
        if 'initial_padding' in filtered_data: filtered_data['initial_padding'] = safe_int(
            filtered_data['initial_padding'])
        # Ensure dict fields are present even if empty in source
        if 'disposition' not in filtered_data: filtered_data['disposition'] = {}
        if 'tags' not in filtered_data: filtered_data['tags'] = {}

        return cls(**filtered_data)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FormatInfo:
    """Represents information about the media container format."""
    filename: typing.Optional[str] = None
    nb_streams: typing.Optional[int] = None
    nb_programs: typing.Optional[int] = None
    format_name: typing.Optional[str] = None
    format_long_name: typing.Optional[str] = None
    start_time: typing.Optional[float] = None
    duration: typing.Optional[float] = None
    size: typing.Optional[int] = None
    bit_rate: typing.Optional[int] = None
    probe_score: typing.Optional[int] = None
    tags: typing.Dict[str, str] = field(default_factory=dict)

    @property
    def duration_sec(self) -> typing.Optional[float]:
        if self.duration is not None and self.duration > 0: return self.duration
        return None

    @classmethod
    def from_dict(cls, data: dict) -> 'FormatInfo':
        """Creates FormatInfo from a dictionary."""
        known_fields = {f.name for f in fields(cls) if f.init}
        filtered_data = {k: v for k, v in data.items() if k in known_fields}

        if 'nb_streams' in filtered_data: filtered_data['nb_streams'] = safe_int(filtered_data['nb_streams'])
        if 'nb_programs' in filtered_data: filtered_data['nb_programs'] = safe_int(filtered_data['nb_programs'])
        if 'start_time' in filtered_data: filtered_data['start_time'] = safe_float(filtered_data['start_time'])
        if 'duration' in filtered_data: filtered_data['duration'] = safe_float(filtered_data['duration'])
        if 'size' in filtered_data: filtered_data['size'] = safe_int(filtered_data['size'])
        if 'bit_rate' in filtered_data: filtered_data['bit_rate'] = safe_int(filtered_data['bit_rate'])
        if 'probe_score' in filtered_data: filtered_data['probe_score'] = safe_int(filtered_data['probe_score'])
        if 'tags' not in filtered_data: filtered_data['tags'] = {}

        return cls(**filtered_data)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MediaInfo:
    """Container for format and stream information, parsed from ffprobe."""
    format: typing.Optional[FormatInfo] = None
    streams: typing.List[StreamInfo] = field(default_factory=list)
    raw_dict: typing.Dict = field(default_factory=dict, init=False, repr=False)
    stream_id_map: typing.Dict[str, StreamInfo] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self):
        """Post-initialization tasks (currently empty, map updated externally)."""
        pass  # Map update is handled externally after assigning unique IDs

    def update_stream_id_map(self):
        """
        Helper method to rebuild the stream_id_map.
        Should be called AFTER unique_id has been assigned to all streams.
        """
        self.stream_id_map.clear()
        for stream in self.streams:
            if stream.unique_id:
                self.stream_id_map[stream.unique_id] = stream
            # Note: If unique_id is not assigned, it won't be in the map.

    @classmethod
    def from_ffprobe_dict(cls, data: dict) -> 'MediaInfo':
        """Creates MediaInfo from the full ffprobe JSON output dictionary."""
        format_info = FormatInfo.from_dict(data.get('format', {})) if 'format' in data else None
        streams_info = [StreamInfo.from_dict(s) for s in data.get('streams', [])]
        # Create instance without raw_dict and stream_id_map
        instance = cls(format=format_info, streams=streams_info)
        # Assign raw_dict after creation
        instance.raw_dict = data
        # stream_id_map needs update_stream_id_map() called later
        return instance

    def get_stream(self, index: int) -> typing.Optional[StreamInfo]:
        """Gets a stream by its original index field."""
        return next((s for s in self.streams if s.index == index), None)

    def get_stream_by_id(self, unique_id: str) -> typing.Optional[StreamInfo]:
        """Gets a stream by its assigned unique_id (requires map to be updated)."""
        return self.stream_id_map.get(unique_id)

    def get_streams_by_type(self, codec_type: str) -> typing.List[StreamInfo]:
        """Gets all streams of a specific codec type."""
        return [s for s in self.streams if s.codec_type == codec_type]
