"""Submit release checks and present their outcomes on the GUI thread."""

from typing import Callable
from pathlib import Path
from PySide6.QtWidgets import QDialog, QMessageBox, QWidget

from core.app_metadata import APP_VERSION
from core.jobs import JobState, job_step
from io_modules.update import (
    write_empty_installer, is_installed_windows_app, write_installer, read_latest_release,
    remove_installer, resolve_update_offer,
)
from orchestration.jobs import JobRunner
from ._update_dialog import UpdateDialog

_CHECK_TITLE = "Check for Updates"
_UPDATE_TITLE = "Spectra Update"


class UpdateHandler:
    """One shared background path for startup and manual Update checks."""

    def __init__(self, job_runner: JobRunner, parent_widget: QWidget,
                 install_update: Callable[[Path], bool] | None):
        self.job_runner = job_runner
        self.parent_widget = parent_widget
        self._checking = False
        self._manual = False
        # Set for exactly as long as a download job owns the temporary installer.
        self._download: tuple[int | None, Path] | None = None
        self._install_update = install_update

    def run_startup_check(self) -> None:
        self._run_check(manual=False)

    def run_manual_check(self) -> None:
        self._run_check(manual=True)

    def _run_check(self, *, manual: bool) -> None:
        if self._download is not None:
            if manual:
                self._tell(QMessageBox.information, _CHECK_TITLE, "An Update is already downloading.")
            return
        # A manual request during startup promotes that check's feedback.
        if self._checking:
            self._manual = self._manual or manual
            return
        self._checking = True
        self._manual = manual
        self.job_runner.submit(
            _CHECK_TITLE,
            steps=[job_step("Read latest release", read_latest_release)],
            lane="interactive", quiet=True,
            on_step=self._show_release, on_error=self._show_error,
            on_done=self._finish_check,
        )

    def _tell(self, show: Callable, title: str, text: str) -> None:
        """Message boxes only while the window is up; a closing window stays quiet."""
        if self.parent_widget.isVisible():
            show(self.parent_widget, title, text)

    def _show_release(self, release: dict | None, index: int) -> None:
        if not self.parent_widget.isVisible():
            return
        offer = resolve_update_offer(release, APP_VERSION)
        if offer is None:
            if self._manual:
                self._tell(QMessageBox.information, _CHECK_TITLE, "You are up to date.")
            return
        if UpdateDialog(offer, self.parent_widget).exec() == QDialog.DialogCode.Accepted:
            self._run_download(offer)

    def _run_download(self, offer) -> None:
        if self._install_update is None or not is_installed_windows_app():
            self._tell(QMessageBox.information, _UPDATE_TITLE,
                       "In-app Update is available in installed Windows Spectra.")
            return
        try:
            destination = write_empty_installer()
        except OSError:
            self._show_download_error()
            return
        # Recorded before submit: on_done may arrive before submit returns.
        self._download = (None, destination)
        job_id = self.job_runner.submit(
            f"Download Spectra {offer.app_version}",
            steps=[job_step("Download installer", write_installer,
                            offer.installer_url, destination)],
            lane="interactive", quiet=False,
            cancel_token_keyword="cancel_token", progress_keyword="progress_fn",
            on_error=lambda message, index: self._show_download_error(),
            on_done=lambda record: self._finish_download(record, destination),
        )
        if self._download is not None:
            self._download = (job_id, destination)

    def cancel_download(self) -> None:
        """Unlink before shutdown can terminate a stalled network worker."""
        if self._download is not None:
            job_id, destination = self._download
            self._download = None
            if job_id is not None:
                self.job_runner.cancel(job_id)
            remove_installer(destination)

    def _show_download_error(self) -> None:
        self._tell(QMessageBox.warning, _UPDATE_TITLE, "Update download failed. Please try again later.")

    def _finish_download(self, record, destination: Path) -> None:
        """The only owner of a finished download's file: install it or remove it."""
        if self._download is None:
            return  # cancel_download already removed it.
        # Cleared first: installing closes the window, whose cancel_download
        # must not delete the installer the detached process is about to run.
        self._download = None
        if (record.state is JobState.DONE and not record.errors
                and self.parent_widget.isVisible()
                and self._install_update(destination)):
            return
        remove_installer(destination)

    def _show_error(self, message: str, index: int) -> None:
        if self._manual:
            self._tell(QMessageBox.warning, _CHECK_TITLE, "Update check failed. Please try again later.")

    def _finish_check(self, record) -> None:
        self._checking = False
