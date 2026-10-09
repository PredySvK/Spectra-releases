# core/models.py
"""
Core structural data models representing industrial signal layout metrics.
Features automated dictionary serialization wrappers to enforce strict open-window session isolation.
All internal documentation strings and variable labels are standardly written in English.
"""

from typing import Dict, Any, List, Optional, Tuple
from core.block_kinds import KIND_TIME_RESPONSE

# A physical channel identified by (base_name, direction) rather than by its raw
# label -- the same sensor's label can carry a different "Set #N" prefix from
# file to file. Lives here rather than beside its first user
# (selection.measurement_selection) because core.measurement_selection
# needs it too, and core/ must not import io_modules/.
ChannelIdentity = Tuple[str, Optional[str]]


# UFF dataset 58 function code of a time response, the only kind a reader can
# turn into a waveform. Also the default for a channel without a code.
FUNC_TYPE_TIME_RESPONSE = 1

# UFF dataset 58 code of an order function -- what an Imported result's
# channel is (§1.134). Not a time response, so computations skip it.
FUNC_TYPE_ORDER_FUNCTION = 28


def is_time_response(func_type: int) -> bool:
    """Only UFF time responses are readable waveforms (ADR §1.24).

    A channel without a function code is a time response: ChannelMetadata
    defaults func_type to FUNC_TYPE_TIME_RESPONSE, and so must a reader of a
    legacy snapshot.
    """
    return int(func_type) == FUNC_TYPE_TIME_RESPONSE


def resolve_channel_block_kind(channel: 'ChannelMetadata') -> Optional[str]:
    """The readable block kind, including legacy waveform indexes.

    Unsupported UNV function codes have no readable block kind.
    """
    return getattr(channel, "block_kind", None) or (
        KIND_TIME_RESPONSE if is_time_response(getattr(channel, "func_type", 1)) else None
    )


class ChannelMetadata:
    """
    Data descriptor storing physical sensor tracking properties and sampling criteria.
    Encapsulates serialization algorithms to insulate I/O operations from schema drift.
    """

    def __init__(self, index: int, name: str, channel_type: str, unit: str):
        self.index: int = index
        self.name: str = name
        self.type: str = channel_type
        self.unit: str = unit

        # Physics dimension indicators fallback baselines
        self.func_type: int = FUNC_TYPE_TIME_RESPONSE
        self.block_kind: Optional[str] = None  # Explicit for Imported results; legacy waveforms use func_type.
        self.abscissa_inc: float = 0.0
        self.abscissa_min: float = 0.0
        self.num_pts: int = 0
        self.sampling_rate: float = 0.0
        self.ordinate_axis_units_lab: str = unit

        # Degrees of Freedom tracking for FEM correlation
        self.rsp_node: int = 0
        self.rsp_dir: int = 0
        self.ref_node: int = 0
        self.ref_dir: int = 0

        # Per-dataset UFF identification fields (BUGS.md N1/N2) -- one value
        # per channel, not per file: a UNV file's 58-blocks each carry their
        # own id1..id5, and a reader with no such concept (.asc) simply never
        # sets them, which the Metadata Editor's "channel" layer already
        # treats as "no value here" rather than assuming UNV.
        self.id1: Optional[str] = None
        self.id2: Optional[str] = None
        self.id3: Optional[str] = None
        self.id4: Optional[str] = None
        self.id5: Optional[str] = None

    def to_dict(self) -> dict:
        """
        Dumps all local instance hardware attributes dynamically into a clean database row map.
        Protects internal private operational slot markers from exploding the JSON cache limits.
        """
        export_dict = {}
        if hasattr(self, '__dict__'):
            for key, val in self.__dict__.items():
                if not key.startswith('_'):
                    export_dict[key] = val
        return export_dict

    @classmethod
    def from_dict(cls, data_map: dict) -> 'ChannelMetadata':
        """
        Factory reconstruction routine instantiating a fresh ChannelMetadata entity state.
        Dynamically loops over keys array bounds to shield the structure against future UNV updates.
        """
        instance = cls(
            index=data_map.get("index", 0),
            name=data_map.get("name", "Unknown_Channel"),
            channel_type=data_map.get("type", "general_dynamic"),
            unit=data_map.get("unit", "dimensionless")
        )

        for key, val in data_map.items():
            if key not in ["index", "name", "type", "unit"]:
                setattr(instance, key, val)

        return instance
class MeasurementRunIndex:
    """
    Top-level index descriptor holding metadata and channels lists for a single UNV recording sheet file.
    Isolated per-window instance context to support multi-session powertrain analysis.
    """

    def __init__(self, file_name: str, file_path: str):
        self.file_name: str = file_name
        self.file_path: str = file_path

        # Layer 2: Dictionary layout holding relational Excel metadata test logs columns
        self.metadata: Dict[str, Any] = {}

        # Layer 1: Strong references holding discovered hardware sub-channels metadata
        self.available_channels: Dict[str, ChannelMetadata] = {}

    def add_channel_metadata(self, unique_label: str, channel_meta: ChannelMetadata):
        """Registers a discovered sub-channel element securely into the active tracking dictionary loop."""
        self.available_channels[unique_label] = channel_meta

    def readable_channels(self) -> List[ChannelMetadata]:
        """The channels a reader can turn into a waveform. The rest stay in
        available_channels so the file's contents remain visible."""
        return [meta for meta in self.available_channels.values()
                if is_time_response(meta.func_type)]

    # Attributes that describe the run's own structure rather than a Level 1
    # fact discovered from the file -- excluded from file_level_facts() below.
    _STRUCTURAL_ATTRS = {"file_name", "file_path", "metadata", "available_channels"}

    def file_level_facts(self) -> Dict[str, Any]:
        """
        Every file-level fact a reader discovered directly from the measurement
        file (Level 1) -- id1..id5 today, and whatever a future reader for a
        different file type sets besides, picked up automatically the same way
        ChannelMetadata.to_dict() already works for per-channel facts. This is
        what session.project persists onto SourceEntry.file_metadata
        so it survives without the data root being mounted.
        """
        return {
            key: value for key, value in self.__dict__.items()
            if not key.startswith("_") and key not in self._STRUCTURAL_ATTRS
        }











