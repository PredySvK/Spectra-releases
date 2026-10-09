"""Pure decisions for pairing channels dropped on a spectrogram dock."""

from dataclasses import dataclass
from typing import Any, Literal


SpectrogramDropAction = Literal["reject", "replace", "wait", "compute"]


@dataclass(frozen=True)
class SpectrogramDropDecision:
    """The data-only result of routing one channel to a spectrogram."""

    action: SpectrogramDropAction
    vib_block: Any = None
    tacho_block: Any = None
    messages: tuple[str, ...] = ()

    @property
    def is_rejected(self) -> bool:
        return self.action == "reject"

    @property
    def should_compute(self) -> bool:
        return self.action in ("replace", "compute")


def decide_spectrogram_drop(
    data_block: Any,
    existing_vib_block: Any,
    existing_tacho_block: Any,
    tracking_mode: str,
    *,
    channel_name: str,
) -> SpectrogramDropDecision:
    """Decide how a dropped channel changes a spectrogram's channel pair.

    The caller supplies already-read blocks and applies the returned state.
    This function does not inspect or mutate a dock, log, or dispatch work.
    """
    channel_type = data_block.channel_type
    is_tacho = channel_type == "tacho"
    other = existing_vib_block if is_tacho else existing_tacho_block
    source_path = data_block.source.file_path

    if other is not None and other.source.file_path != source_path:
        return SpectrogramDropDecision(
            "reject",
            existing_vib_block,
            existing_tacho_block,
            (
                f"ERROR: '{channel_name}' comes from a different file than the channel already "
                "on this spectrogram. Vibration and tacho must come from the same measurement.",
            ),
        )

    messages: list[str] = []
    vib_block = existing_vib_block
    tacho_block = existing_tacho_block

    if is_tacho:
        if existing_tacho_block is not None:
            messages.append(f"SYSTEM: Replacing previous tacho channel with '{channel_name}'.")
        tacho_block = data_block
        if vib_block is None:
            messages.append("SYSTEM: Tacho registered. Drop a vibration channel to build the waterfall.")
            return SpectrogramDropDecision("wait", vib_block, tacho_block, tuple(messages))
        messages.append("SYSTEM: Tacho registered. Computing waterfall...")
    else:
        if existing_vib_block is not None:
            messages.append(f"SYSTEM: Replacing previous spectrogram channel with '{channel_name}'.")
        vib_block = data_block

    if tracking_mode == "rpm" and tacho_block is None:
        messages.append("SYSTEM: Vibration loaded. Drop a tacho channel to build the waterfall.")
        return SpectrogramDropDecision("wait", vib_block, tacho_block, tuple(messages))

    action = "replace" if (is_tacho and existing_tacho_block is not None) or (
        not is_tacho and existing_vib_block is not None
    ) else "compute"
    return SpectrogramDropDecision(action, vib_block, tacho_block, tuple(messages))
