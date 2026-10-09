# Updates

Spectra can check for a newer stable release and, in the installed Windows app, download and start its installer. You can check manually from Settings, or let the app check once after startup.

## Check for an update

On the **Settings** tab, choose **Check for Updates**. At startup, Spectra starts the same check after its window appears. The check reads the latest release information from GitHub in the background, so the window stays responsive.

Spectra offers an update only when the release is newer than the version you are using, is not marked as a draft or prerelease, and includes the matching `Spectra-<version>-setup.exe` installer. The offer shows the release notes when available; otherwise it says **No patch notes provided.** Choose **Update now** to continue or **Later** to close the offer and keep working. **Later** is the default choice.

If a manual check finds no newer eligible release, Spectra says **You are up to date.** A startup check stays quiet when there is no offer. If a check fails, a manual check shows a warning; a failed startup check stays quiet. A missing stable release on GitHub is treated as no update being available. If a manual check is already running when you click the button, it does not start a second check; its result is shown when ready. While a download is running, another manual check tells you an Update is already downloading.

## What's new

When no project is open, the Welcome page shows a scrollable **What's new** list under **Recent** ([projects](topic:general/projects)): every released version as `version - release date`, followed by what changed. Screenshots of a change appear under it. It works offline; the list ships with the app.

## Download and cancel

In-app installation is available only in the installed Windows version of Spectra. If you accept an offer in another environment, Spectra explains that the feature is available in installed Windows Spectra; it does not download the installer there.

After you choose **Update now** in the installed app, Spectra downloads the installer to a temporary file. The download appears among the [running jobs](topic:jobs/intro) with progress and a **Cancel** action. You can cancel it from the job status strip or select it in the *Jobs* panel and choose **Cancel Selected** (or **Cancel All**). A failed or cancelled download is removed. If the download fails, Spectra shows **Update download failed. Please try again later.**

## Close Spectra and install

After the download finishes, Spectra follows its normal close procedure before starting the installer:

1. If a visible batch job is still running, confirm that it should be cancelled before closing.
2. If the [project](topic:general/projects) has unsaved changes, choose **Save**, **Discard**, or **Cancel**. A project with loaded data that has never been saved also offers to save. **Cancel**, or a failed save, keeps Spectra open and prevents the installation from starting.
3. Spectra saves its window and layout settings, closes its workspace, then launches the downloaded installer.

The installer runs silently into the folder containing the current Spectra executable and is asked to restart the app when installation finishes. If the installer cannot be started, Spectra shows a warning and closes without updating; start the app again to retry.

If checking or downloading fails, try again later with a working Internet connection. See [Jobs](topic:jobs/intro) for the job controls and [Projects](topic:general/projects) for saving your work.
