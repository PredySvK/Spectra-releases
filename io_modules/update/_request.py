"""Build the HTTP request every Update network call shares."""

from urllib.request import Request

from core.app_metadata import APP_NAME, APP_VERSION


def build_request(url: str, **headers: str) -> Request:
    """Request for ``url`` that identifies this App version to GitHub."""
    return Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}", **headers})
