"""Decide whether a published release offers a newer App version."""

from dataclasses import dataclass, field
import re

from core.app_metadata import RELEASES_REPO


@dataclass(frozen=True)
class UpdateOffer:
    """A newer App version, its patch notes and installer download URL."""

    app_version: str
    notes: str
    installer_url: str
    images: dict[str, bytes] = field(default_factory=dict)  # screenshot URL -> file bytes


def _app_version(value: object) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not re.fullmatch(r"v?[0-9]{1,9}\.[0-9]{1,9}\.[0-9]{1,9}", value):
        return None
    major, minor, patch = map(int, value.removeprefix("v").split("."))
    return major, minor, patch


def resolve_update_offer(release_json: object, current_app_version: str) -> UpdateOffer | None:
    """Return an offer only for a valid newer stable release with its installer."""
    if not isinstance(release_json, dict):
        return None
    if release_json.get("draft") is not False or release_json.get("prerelease") is not False:
        return None
    tag = release_json.get("tag_name")
    latest = _app_version(tag)
    current = _app_version(current_app_version)
    if latest is None or current is None or latest <= current:
        return None
    app_version = str(tag).removeprefix("v")
    assets = release_json.get("assets")
    notes = release_json.get("body")
    if not isinstance(assets, list) or (notes is not None and not isinstance(notes, str)):
        return None
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != f"Spectra-{app_version}-setup.exe":
            continue
        url = asset.get("browser_download_url")
        if not isinstance(url, str) or not url.startswith(f"https://github.com/{RELEASES_REPO}/releases/download/"):
            continue
        return UpdateOffer(app_version, notes or "", url, release_json.get("images") or {})
    return None
