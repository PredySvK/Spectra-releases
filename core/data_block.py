# =====================================================================
# FILE: core/data_block.py
# =====================================================================
"""
The one carrier every measurement and every result travels in.

One carrier, not a subclass per result type: the maths lives in
signal_processing/dsp as free numpy functions and the drawing lives in the
renderers, so a block has no behaviour of its own to specialise. What it does
have is four independent axes of description -- shape, meaning, units and
processing parameters -- which a single inheritance chain would have to
linearise. UFF dataset 58, the format this tool reads, makes the same call:
one record type plus independent codes. See ARCHITECTURE_DECISIONS §1.18.

Three rules hold everything together:

  * `kind` is the discriminator. core/block_kinds.py says what each kind needs.
  * The block's own view of `values` is frozen (`values.flags.writeable is
    False`). `_readonly` takes a *view*, though, so a caller that keeps a
    writable reference to the same buffer can still change what the block sees
    -- hand blocks fresh arrays. A block sent down two branches of a workflow
    must come out of both the same; the old in-place `y_data =
    remove_dc_offset(y_data)` made the result depend on which branch ran first.
    Change means a new block via dataclasses.replace.
  * Fields the code branches on or computes with are typed. `metadata` is only
    what gets shown to the user.
"""

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np

from core.block_kinds import (
    KIND_ORDER_CUT, KIND_ORDER_RESIDUAL, KIND_OVERALL_LEVEL, KIND_SPECTROGRAM, KIND_SPECTRUM, KIND_TIME_RESPONSE,
    META_EFFECTIVE_F_START, META_EFFECTIVE_F_STOP, PARAM_F_START, PARAM_F_STOP, PARAM_ORDER,
    RMS_PEAK_CURVE_KINDS, STEP_READ,
    validate,
)
from core.dsp_configs import (
    VALID_AMPLITUDE_MODES,
    VALID_SPECTRUM_FORMATS,
    normalize_dsp_choice,
)
from core.scaling_table import scale_canonical_to_amplitude
from core.units import (
    format_order_unit,
    format_spectral_unit,
    strip_amplitude_suffix,
)


def _readonly(values) -> np.ndarray:
    """
    A read-only view of `values`.

    frozen=True stops the field being rebound; it does nothing about the array
    behind it, so without this the immutability guarantee would be decorative.
    A fresh view is taken rather than flipping the caller's own array: handing
    an array to a block must not silently lock the caller's copy of it.
    """
    array = np.asarray(values)
    if array.flags.writeable:
        array = array.view()
        array.flags.writeable = False
    return array


@dataclass(frozen=True)
class Axis:
    """One axis of a block: its sample positions and what they mean."""
    values: np.ndarray
    unit: str                    # "s" | "Hz" | "RPM" | "order" | ...
    quantity: str                # "time"|"frequency"|"order"|"rpm"|"cycles"|"quefrency"|"angle"
    label: str = ""

    def __post_init__(self):
        object.__setattr__(self, "values", _readonly(self.values))

    # Spacing is deliberately not stored. An octave analysis (Epic 7) has
    # unequally spaced bands, and anything that needs a step either derives it
    # from these values or reads acquisition.dt.


@dataclass(frozen=True)
class SourceRef:
    """Where the numbers came from. Travels unchanged into every result."""
    file_path: str = ""
    file_name: str = ""
    channel_index: int = -1
    channel_name: str = ""
    # Level 2 Excel facts. Stays a loose mapping until §1.1 gives it a typed
    # schema -- that change then touches the value type here and nothing else.
    excel_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Acquisition:
    """
    Physics of the recording. Derived blocks inherit it unchanged: a spectrum
    still came off a recording sampled at dt, and the response/reference nodes
    still identify the physical measurement point.
    """
    dt: float = 0.0              # sampling period; was metadata["abscissa_inc"]
    abscissa_min: float = 0.0
    num_pts: int = 0
    recorded_unit: str = ""      # unit as written in the file, before any correction
    rsp_node: int = 0
    rsp_dir: int = 0
    ref_node: int = 0
    ref_dir: int = 0


@dataclass(frozen=True)
class SpectralProcessing:
    """
    The DSP settings a result was produced with. Absent (None) on a recording:
    a time block claiming window_type="uniform" and acf=1.0, as the flat block
    did, cannot be told apart from one that really was windowed uniformly.

    window_type and enbw_hz are written but not read back today. They stay:
    enbw_hz is what makes a PSD overall-level cursor correct, and window_type
    belongs in the report header (Epic 8).
    """
    window_type: str
    amplitude_mode: str          # "peak" | "rms" | "peak_to_peak"
    spectrum_format: str         # "linear" | "power" | "psd" | "esd" | "canonical"
    acf: float = 1.0             # Amplitude Correction Factor
    ecf_linear: float = 1.0      # Energy Correction Factor (linear RMS)
    enbw_hz: Optional[float] = None
    fft_size: Optional[int] = None
    averaging_type: Optional[str] = None
    exponential_alpha: Optional[float] = None


@dataclass(frozen=True)
class Provenance:
    """What was done to get here."""
    step: str = ""                       # "read" | "compute_spectrum" | "compute_order_cuts" | ...
    parents: Tuple[str, ...] = ()        # parent block names; no block_id until a runner needs one
    params: Mapping[str, Any] = field(default_factory=dict)   # serialisable, e.g. {PARAM_ORDER: 2.0}
    algorithm_version: Optional[int] = None


def display_meta_from(source: SourceRef, channel_type: str,
                      metadata: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """
    The flat dict the plotting layer takes as `source_meta`: legend text, unit
    conversion and duplicate-drop detection all read it.

    A free function and not only a method, because a curve drawn straight out
    of the result cache has arrays and a label but no block, and has to be able
    to produce the same shape. NVHDataBlock.display_meta() delegates here.
    """
    meta: Dict[str, Any] = {
        "file_path": source.file_path,
        "file_name": source.file_name,
        "channel_index": source.channel_index,
        "channel_type": channel_type,
    }
    if source.excel_metadata:
        meta["excel_metadata"] = dict(source.excel_metadata)
    if metadata:
        meta.update(metadata)
    return meta


@dataclass(frozen=True)
class RawChannel:
    """
    What a reader can honestly know from a file on its own: samples, their
    abscissa, and the acquisition header around them.

    Readers stop short of a finished block because they cannot classify a
    channel -- that is decided from unit and name one layer up -- and a block
    built here would have had to be corrected afterwards. Correcting it
    afterwards is exactly what frozen blocks rule out, so DataAccessor gets the
    parts and assembles once.
    """
    name: str
    values: np.ndarray
    times: np.ndarray
    acquisition: Acquisition


@dataclass(frozen=True)
class NVHDataBlock:
    name: str
    kind: str                              # the discriminator -- see core/block_kinds.py
    axes: Tuple[Axis, ...]                 # 1 = curve, 2 = map; len(axes) == values.ndim
    values: np.ndarray
    value_unit: str = "dimensionless"
    value_quantity: str = ""
    channel_type: str = "unknown"          # "accelerometer" | "microphone" | "tacho" | "voltage" | ...
    acquisition: Acquisition = field(default_factory=Acquisition)
    processing: Optional[SpectralProcessing] = None
    source: SourceRef = field(default_factory=SourceRef)
    provenance: Provenance = field(default_factory=Provenance)
    metadata: Mapping[str, Any] = field(default_factory=dict)   # display-only leftovers

    def __post_init__(self):
        # Freezing and validation sit here rather than in the factories so that
        # dataclasses.replace -- the sanctioned way to change a block -- cannot
        # produce an unvalidated or writeable one either.
        object.__setattr__(self, "axes", tuple(self.axes))
        object.__setattr__(self, "values", _readonly(self.values))
        validate(self)

    # -- reading ----------------------------------------------------------

    @property
    def primary_axis(self) -> Axis:
        """The axis a 1D curve is drawn against; for a map, its first."""
        return self.axes[0]

    @property
    def is_canonical(self) -> bool:
        """True if this block holds canonical bin energy (g^2) rather than pre-scaled values."""
        if self.kind not in (KIND_SPECTRUM, KIND_SPECTROGRAM):
            return False
        if self.processing is None:
            return False
        fmt = (self.processing.spectrum_format or "").lower().strip()
        if fmt == "canonical":
            return True
        if fmt not in ("linear", "power", "psd", "esd"):
            unit = self.value_unit.strip()
            if unit.endswith("^2") or unit.endswith("²") or ")^2" in unit:
                return True
        return False

    def to_display_values(
        self,
        spectrum_format: str = "linear",
        amplitude_mode: str = "rms",
    ) -> Tuple[np.ndarray, str]:
        """
        Safe programmatic access to linear/scaled values and display unit (ADR §1.60, §1.61).

        For spectral blocks (carrying canonical bin energy P_canon in g^2 -- an invariant of
        KIND_SPECTRUM/KIND_SPECTROGRAM, not a branch), computes the requested Format x
        Amplitude view on-the-fly via core.scaling_table and generates the display unit.
        For order cut and Overall Level blocks, scales Peak as sqrt(2) * y_rms and formats the unit.
        For other blocks, returns (values, value_unit).
        """
        if self.kind in (KIND_SPECTRUM, KIND_SPECTROGRAM):
            amplitude_mode = normalize_dsp_choice(amplitude_mode, VALID_AMPLITUDE_MODES, "amplitude_mode")
            spectrum_format = normalize_dsp_choice(spectrum_format, VALID_SPECTRUM_FORMATS, "spectrum_format")

            acf = float(self.processing.acf) if (self.processing and self.processing.acf) else 1.0
            ecf_linear = float(self.processing.ecf_linear) if (self.processing and self.processing.ecf_linear) else 1.0
            acf_ecf = acf / ecf_linear

            freq_axis = self.axes[0]
            n_freqs = len(freq_axis.values)
            if n_freqs > 1:
                df = float(freq_axis.values[1] - freq_axis.values[0])
            elif self.processing and self.processing.enbw_hz:
                df = float(self.processing.enbw_hz) / (acf_ecf ** 2)
            else:
                df = 1.0

            fft_size = self.processing.fft_size if (self.processing and self.processing.fft_size) else (2 * (n_freqs - 1))

            scaled = scale_canonical_to_amplitude(
                self.values, spectrum_format=spectrum_format, amplitude_mode=amplitude_mode,
                acf=acf, ecf_linear=ecf_linear, df=df, fft_size=fft_size,
            )

            base_unit = strip_amplitude_suffix(self.value_unit)
            display_unit = format_spectral_unit(base_unit, spectrum_format, amplitude_mode)
            return scaled, display_unit

        if self.kind in RMS_PEAK_CURVE_KINDS:
            amplitude_mode = normalize_dsp_choice(amplitude_mode, VALID_AMPLITUDE_MODES, "amplitude_mode")
            if amplitude_mode == "peak":
                scaled = self.values * np.sqrt(2.0)
            else:
                scaled = np.asarray(self.values)
            display_unit = format_order_unit(self.value_unit, "linear", amplitude_mode)
            return scaled, display_unit

        return np.asarray(self.values), self.value_unit

    def display_meta(self) -> Dict[str, Any]:
        """
        This block's identity as a `source_meta` dict -- see display_meta_from.

        Derived on demand, never stored: the typed fields stay the single
        truth. The old block carried channel_type both typed and in its
        metadata dict, with graph_dock copying one into the other on every plot.
        """
        return display_meta_from(self.source, self.channel_type, self.metadata)

    def inherited_context(self) -> Dict[str, Any]:
        """
        The fields a result computed from this block keeps unchanged: which
        sensor it is, how it was recorded, and what to show about it. Spread
        into the factory call by every builder in result_blocks.
        """
        return {
            "channel_type": self.channel_type,
            "acquisition": self.acquisition,
            "source": self.source,
            "metadata": self.metadata,
        }

    # -- construction ------------------------------------------------------
    #
    # One factory per kind, and they are the only way blocks are built outside
    # this module (tests/test_architecture.py enforces it). Before them, an
    # order cut was assembled at four separate call sites and a spectrum at
    # two, each spelling out ten fields and free to disagree about one.

    @staticmethod
    def _carry_through(acquisition: Optional[Acquisition],
                       source: Optional[SourceRef],
                       provenance: Optional[Provenance],
                       metadata: Optional[Mapping[str, Any]], *,
                       provenance_default: Optional[Provenance] = None) -> Dict[str, Any]:
        """
        The four fields every factory resolves the same way: an explicit value
        wins, otherwise the type's own empty default. Spelt out once here rather
        than as four `x if x is not None else X()` lines repeated in each
        factory, where the copies were free to drift apart.
        """
        return {
            "acquisition": acquisition if acquisition is not None else Acquisition(),
            "source": source if source is not None else SourceRef(),
            "provenance": provenance if provenance is not None
            else (provenance_default if provenance_default is not None else Provenance()),
            "metadata": metadata if metadata is not None else {},
        }

    @classmethod
    def from_stored(cls, *, name: str, kind: str, axes: Tuple[Axis, ...], values,
                    value_unit: str = "dimensionless", value_quantity: str = "",
                    channel_type: str = "unknown",
                    acquisition: Optional[Acquisition] = None,
                    processing: Optional[SpectralProcessing] = None,
                    source: Optional[SourceRef] = None,
                    provenance: Optional[Provenance] = None,
                    metadata: Optional[Mapping[str, Any]] = None) -> "NVHDataBlock":
        """
        Rebuilds a block that was already validated once, on its way out to disk.

        The inverse of serialisation, and the only reason it takes `kind` and
        finished `axes` instead of naming them per kind like the factories do:
        the result cache (§1.21) stores whatever kinds core/block_kinds.py
        registers, so a per-kind branch there would reintroduce exactly the
        `if/elif` the register exists to abolish. Validation still runs -- a
        corrupt or hand-edited cache file cannot smuggle an incoherent block in.

        Not for computed results. Anything the DSP produces goes through the
        factory for its kind, which is what fixes the axis units and quantities;
        this one trusts what it is handed.
        """
        return cls(
            name=name, kind=kind, axes=axes, values=values,
            value_unit=value_unit, value_quantity=value_quantity,
            channel_type=channel_type, processing=processing,
            **cls._carry_through(acquisition, source, provenance, metadata),
        )

    @classmethod
    def time_response(cls, *, name: str, values, times, value_unit: str = "dimensionless",
                      time_unit: str = "s", channel_type: str = "unknown",
                      acquisition: Optional[Acquisition] = None,
                      source: Optional[SourceRef] = None,
                      provenance: Optional[Provenance] = None,
                      metadata: Optional[Mapping[str, Any]] = None) -> "NVHDataBlock":
        return cls(
            name=name, kind=KIND_TIME_RESPONSE,
            axes=(Axis(values=times, unit=time_unit, quantity="time", label="Time"),),
            values=values, value_unit=value_unit, value_quantity="amplitude",
            channel_type=channel_type,
            **cls._carry_through(acquisition, source, provenance, metadata,
                                 provenance_default=Provenance(step=STEP_READ)),
        )

    @classmethod
    def spectrum(cls, *, name: str, values, frequencies, value_unit: str,
                 processing: SpectralProcessing, channel_type: str = "unknown",
                 acquisition: Optional[Acquisition] = None,
                 source: Optional[SourceRef] = None,
                 provenance: Optional[Provenance] = None,
                 metadata: Optional[Mapping[str, Any]] = None) -> "NVHDataBlock":
        return cls(
            name=name, kind=KIND_SPECTRUM,
            axes=(Axis(values=frequencies, unit="Hz", quantity="frequency", label="Frequency"),),
            values=values, value_unit=value_unit, value_quantity="amplitude",
            channel_type=channel_type, processing=processing,
            **cls._carry_through(acquisition, source, provenance, metadata),
        )

    @classmethod
    def spectrogram(cls, *, name: str, values, frequencies, z_values, z_unit: str,
                    z_quantity: str, value_unit: str, processing: SpectralProcessing,
                    channel_type: str = "unknown",
                    acquisition: Optional[Acquisition] = None,
                    source: Optional[SourceRef] = None,
                    provenance: Optional[Provenance] = None,
                    metadata: Optional[Mapping[str, Any]] = None) -> "NVHDataBlock":
        """`values` is (frequency, z) -- one spectrum column per rpm step or time slice."""
        return cls(
            name=name, kind=KIND_SPECTROGRAM,
            axes=(
                Axis(values=frequencies, unit="Hz", quantity="frequency", label="Frequency"),
                Axis(values=z_values, unit=z_unit, quantity=z_quantity,
                     label="Speed" if z_quantity == "rpm" else "Time"),
            ),
            values=values, value_unit=value_unit, value_quantity="amplitude",
            channel_type=channel_type, processing=processing,
            **cls._carry_through(acquisition, source, provenance, metadata),
        )

    @classmethod
    def order_cut(cls, *, name: str, values, rpm, order: Optional[float], value_unit: str,
                  processing: Optional[SpectralProcessing], channel_type: str = "unknown",
                  acquisition: Optional[Acquisition] = None,
                  source: Optional[SourceRef] = None,
                  provenance: Optional[Provenance] = None,
                  metadata: Optional[Mapping[str, Any]] = None) -> "NVHDataBlock":
        """
        `order` lands in provenance.params[PARAM_ORDER]: it is
        the parameter that produced this cut, not a property of the numbers.
        Callers used to parse it back out of the display name with a str.split.

        An Imported result passes processing=None with Provenance(step=STEP_READ),
        and order=None when its file does not say which order it is.
        """
        lineage = provenance if provenance is not None else Provenance()
        params = dict(lineage.params)
        params[PARAM_ORDER] = order
        return cls(
            name=name, kind=KIND_ORDER_CUT,
            axes=(Axis(values=rpm, unit="RPM", quantity="rpm", label="Speed"),),
            values=values, value_unit=value_unit, value_quantity="amplitude",
            channel_type=channel_type, processing=processing,
            **cls._carry_through(acquisition, source, replace(lineage, params=params), metadata),
        )

    @classmethod
    def overall_level(cls, *, name: str, values, axis_values, axis_quantity: str,
                      f_start: float, f_stop: Optional[float],
                      effective_f_start: float, effective_f_stop: float,
                      value_unit: str, processing: SpectralProcessing,
                      channel_type: str = "unknown",
                      acquisition: Optional[Acquisition] = None,
                      source: Optional[SourceRef] = None,
                      provenance: Optional[Provenance] = None,
                      metadata: Optional[Mapping[str, Any]] = None) -> "NVHDataBlock":
        """
        `axis_quantity` is "rpm" or "time". The requested band goes to
        provenance.params and the effective one to metadata -- see PARAM_F_START
        in core/block_kinds.py for why they live apart.
        """
        lineage = provenance if provenance is not None else Provenance()
        params = {**lineage.params, PARAM_F_START: f_start, PARAM_F_STOP: f_stop}
        shown = {**(metadata or {}),
                 META_EFFECTIVE_F_START: effective_f_start, META_EFFECTIVE_F_STOP: effective_f_stop}
        if axis_quantity == "rpm":
            axis = Axis(values=axis_values, unit="RPM", quantity="rpm", label="Speed")
        else:
            axis = Axis(values=axis_values, unit="s", quantity=axis_quantity, label="Time")
        return cls(
            name=name, kind=KIND_OVERALL_LEVEL, axes=(axis,),
            values=values, value_unit=value_unit, value_quantity="amplitude",
            channel_type=channel_type, processing=processing,
            **cls._carry_through(acquisition, source, replace(lineage, params=params), shown),
        )

    @classmethod
    def order_residual(cls, *, name: str, values, rpm, value_unit: str,
                       processing: SpectralProcessing, channel_type: str = "unknown",
                       acquisition: Optional[Acquisition] = None,
                       source: Optional[SourceRef] = None,
                       provenance: Optional[Provenance] = None,
                       metadata: Optional[Mapping[str, Any]] = None) -> "NVHDataBlock":
        """A Residual curve against speed (ADR §1.141); its orders ride in `provenance.params`."""
        return cls(
            name=name, kind=KIND_ORDER_RESIDUAL,
            axes=(Axis(values=rpm, unit="RPM", quantity="rpm", label="Speed"),),
            values=values, value_unit=value_unit, value_quantity="amplitude",
            channel_type=channel_type, processing=processing,
            **cls._carry_through(acquisition, source, provenance, metadata),
        )
