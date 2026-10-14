# =====================================================================
# FILE: io_modules/data_accessor.py
# =====================================================================
"""
Data Access Layer (DAL) component.
Responsible for fetching channel data from disk based on the file type.
Strictly separates I/O reading logic from the Application Context.
All internal documentation strings and variable labels are standardly written in English.
"""

from dataclasses import replace

from core.benchmark import benchmark_step
from core.data_block import Acquisition, NVHDataBlock, build_source_ref
from core.models import MeasurementRunIndex, ChannelMetadata
from core.source_amplitude import resolve_rms_factor


class DataAccessor:
    """
    Stateless service routing data read requests to the appropriate file parser.
    """

    @staticmethod
    def fetch_channel_data(run_index: MeasurementRunIndex, channel_meta: ChannelMetadata) -> NVHDataBlock:
        """
        Dynamically selects the correct parser based on file extension, extracts
        the requested channel array, and assembles the standardized NVHDataBlock.

        Assembles rather than patches: readers hand back RawChannel parts
        because they cannot classify a channel -- that is decided here, from the
        unit and name the index layer resolved. The block used to be built by
        the reader and then have y_unit, channel_type and metadata written into
        it afterwards, which a frozen block rules out and which had already
        cost us once: nothing set channel_type at all for a while, so
        remove_dc_offset's tacho guard never matched and speed traces were
        being mean-subtracted.
        """
        try:
            # Same dispatch the folder scan uses -- see open_measurement_reader.
            from io_modules.measurement_files import open_measurement_reader
            with benchmark_step("read"):
                reader = open_measurement_reader(run_index.file_path)
                raw = reader.read_single_channel_data(channel_meta.index)

            if isinstance(raw, NVHDataBlock):
                # An Imported result arrives as a finished block of its kind in
                # the file's own amplitude; the classification, the source and
                # the conversion to RMS are decided here -- the one place.
                return replace(raw, values=raw.values * DataAccessor._resolve_rms_factor(reader, channel_meta),
                               value_unit=channel_meta.unit, channel_type=channel_meta.type,
                               source=build_source_ref(run_index, channel_meta))

            return NVHDataBlock.time_response(
                name=raw.name,
                values=raw.values,
                times=raw.times,
                value_unit=channel_meta.unit,
                channel_type=channel_meta.type,
                acquisition=DataAccessor._build_acquisition(raw.acquisition, channel_meta),
                source=build_source_ref(run_index, channel_meta),
            )

        except Exception as e:
            raise IOError(f"DATA_ACCESS_FAILURE: Failed to read file structure: {str(e)}") from e

    @staticmethod
    def _resolve_rms_factor(reader, channel_meta: ChannelMetadata) -> float:
        """The project's answer for this file, else the reader's default (Source amplitude)."""
        from io_modules.measurement_files import resolve_default_source_amplitude
        source_amplitude = (getattr(channel_meta, "source_amplitude", "")
                            or resolve_default_source_amplitude(type(reader).__name__))
        return resolve_rms_factor(source_amplitude)

    @staticmethod
    def _build_acquisition(raw_acquisition: Acquisition, channel_meta: ChannelMetadata) -> Acquisition:
        """
        The reader knows the dataset it just parsed (node/direction geometry,
        point count, the unit as recorded); the index layer owns the timebase.

        The timebase comes from ChannelMetadata even when it is 0.0. A drag and
        drop builds its ChannelMetadata from the tree descriptor, which carries
        no abscissa_inc, and resolve_sampling_frequency reads that 0.0 as "fall
        back to the spacing of the time array" -- which is the honest answer for
        a channel whose header was never indexed.
        """
        return replace(
            raw_acquisition,
            dt=channel_meta.abscissa_inc,
            abscissa_min=channel_meta.abscissa_min,
        )
