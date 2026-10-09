"""Read public GitHub release metadata without credentials or extra dependencies."""

import json
import re
from urllib.error import HTTPError
from urllib.request import urlopen

from core.app_metadata import RELEASES_REPO
from ._request import build_request


_MAX_IMAGE_BYTES = 5_000_000
_IMAGE_URL = re.compile(r'(?:src="|\]\()(https://github\.com/user-attachments/[^")\s]+)')


def _read_images(notes: object) -> dict[str, bytes]:
    """Screenshots the patch notes show; one that cannot be read is simply left out."""
    images: dict[str, bytes] = {}
    for url in set(_IMAGE_URL.findall(notes if isinstance(notes, str) else "")):
        try:
            with urlopen(build_request(url), timeout=10) as response:
                data = response.read(_MAX_IMAGE_BYTES + 1)
        except OSError:
            continue
        if len(data) <= _MAX_IMAGE_BYTES:
            images[url] = data
    return images


def read_latest_release() -> dict | None:
    """Read the latest stable release with the screenshots its notes show, or None when none is published yet.

    GitHub answers 404 while the releases repository has no stable release;
    every other transport and malformed-response error propagates.
    """
    request = build_request(
        f"https://api.github.com/repos/{RELEASES_REPO}/releases/latest",
        Accept="application/vnd.github+json",
    )
    try:
        with urlopen(request, timeout=10) as response:
            release = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not isinstance(release, dict) or not isinstance(release.get("tag_name"), str):
        raise ValueError("Invalid GitHub release response")
    release["images"] = _read_images(release.get("body"))
    return release
