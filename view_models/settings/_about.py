"""What the About page states about this build: versions of the app and its formats."""

from core.app_metadata import APP_VERSION
from core.dsp_configs import DSP_ALGORITHM_VERSIONS
from core.project_model import PROJECT_FORMAT_VERSION
from io_modules.result_cache import FORMAT_VERSION as RESULT_CACHE_FORMAT_VERSION


def build_about_lines() -> tuple[str, ...]:
    """One entry per label on the About page; the DSP versions are one multi-line entry."""
    dsp_lines = ["DSP algorithms:"] + [
        f"    {kind}: {version}" for kind, version in DSP_ALGORITHM_VERSIONS.items()]
    return (
        f"App version: {APP_VERSION}",
        f"Project file format: {PROJECT_FORMAT_VERSION}",
        f"Result cache format: {RESULT_CACHE_FORMAT_VERSION}",
        "\n".join(dsp_lines),
    )
