_PREFIX = "INFO: Tacho interpolated"


def build_tacho_interpolation_line(file_name: str, tacho_name: str, tacho_rate: float, channel_rate: float) -> str:
    """The log line for one file and one target rate."""
    return (f"{_PREFIX} in {file_name}: {tacho_name} {tacho_rate:g} Hz -> {channel_rate:g} Hz "
            "(the channel's rate).")


def is_tacho_interpolation_line(line: str) -> bool:
    """True for a line `build_tacho_interpolation_line` made."""
    return line.startswith(_PREFIX)
