"""Public release reading and Update offer decisions (ADR §1.140)."""

from ._update_offer import UpdateOffer, resolve_update_offer
from ._release import read_latest_release
from ._installer import (write_empty_installer, is_installed_windows_app, write_installer,
                         remove_installer, run_installer)

__all__ = ["UpdateOffer", "resolve_update_offer", "read_latest_release",
           "write_empty_installer", "is_installed_windows_app", "write_installer", "remove_installer", "run_installer"]
