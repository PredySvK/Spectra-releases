# Windows installer

Run `powershell -ExecutionPolicy Bypass -File packaging\build_exe.ps1` from
any directory, using the script's absolute path when outside the repository.
Requires Python 3.14 (`py`) and Inno Setup 6. The compiler is located on PATH,
in the usual per-user or system folder, or via `-IsccPath <path-to-ISCC.exe>`.

Output: `dist\Spectra\Spectra.exe` and
`dist\Spectra-<APP_VERSION>-setup.exe`. Product version and shortcut
AppUserModelID are read from `core/app_metadata.py`. The installer is unsigned.

The installer needs no elevation, defaults to `%LOCALAPPDATA%\Programs\Spectra`,
and remembers a custom folder on reinstall. Start menu and optional desktop
shortcuts use the application's stable AppUserModelID. Project associations
and the uninstall entry are per-user. Uninstall removes installed files,
shortcuts and associations; it leaves `%LOCALAPPDATA%\Spectra` and QSettings.

The in-app updater downloads in the background with progress and Cancel in
the existing Jobs panel/status strip. It asks the usual window-close questions,
then detaches the installer with the running executable's folder supplied as
`/DIR`. It is available only in the installed Windows application; source runs
can check and view offers but cannot replace their Python environment.

Equivalent manual installer invocation (use `/SILENT` to show installation progress):

```powershell
.\Spectra-0.1.0-setup.exe /SILENT /SUPPRESSMSGBOXES /NORESTART /RESTARTAPP=1 /LOG="setup.log"
```

The updater first lets Spectra ask about running jobs and unsaved work,
then launches the installer and closes. Inno's Restart Manager handles files still in use
without forced termination. `/RESTARTAPP=1` opts into launching Spectra after
a silent install; omit it for unattended deployment without launch. Normal
interactive installation offers a launch checkbox on the final page.

Cancelled/failed downloads and refused updates remove the temporary executable.
A successfully launched executable stays in the user's temp folder because the
installer may still be reading it when Spectra exits.

`licenses/` in the installed folder contains runtime dependency wheel notices,
Python's license, and Qt/PySide upstream license texts. Vendored Qt notices in
`packaging/licenses/` come from PySide `v6.11.1` and Qt base `v6.11.1`:

- https://github.com/pyside/pyside-setup/tree/v6.11.1/LICENSES
- https://github.com/qt/qtbase/tree/v6.11.1/LICENSES
- https://github.com/qt/qtbase/tree/v6.11.1/src/3rdparty
- https://github.com/qt/qtdeclarative/tree/v6.11.1
- https://github.com/qt/qtsvg/tree/v6.11.1
- https://github.com/qt/qtimageformats/tree/v6.11.1
- https://github.com/pyside/pyside-setup/tree/v6.11.1/sources/shiboken6/libshiboken
- https://github.com/qt/qtwebengine/tree/v6.11.1/LICENSES (`licenses/qtwebengine`, Help window)
- https://github.com/qt/qtwebengine-chromium/blob/58c11ad487f8a237cf0ac71cc3e818b52db150df/chromium/LICENSE (Chromium BSD-3, `Chromium-LICENSE.txt`)

Refresh these notices when updating Qt/PySide. LGPL/GPL texts are included
explicitly because these wheels include only the commercial license text.
Qt libraries remain separate replaceable DLLs in the onedir distribution.
The build excludes unused Qt Virtual Keyboard and PDF image plugins.

Manual acceptance on a second Windows PC, with a standard user:

1. Install without UAC, choose a folder, verify Start menu and desktop launch.
2. Double-click a saved `.nvhproject` whose path contains spaces; verify the
   project opens and Explorer displays the Spectra icon.
3. Pin Spectra to the taskbar, close it, reinstall, then launch from the pin.
4. Reinstall interactively and silently; check the previous folder is reused,
   running Spectra is handled, and `/RESTARTAPP=1` launches it afterwards.
5. Change the layout, exit, uninstall, check data/settings remain, then
   reinstall and verify the layout is restored.
6. Install an older release, publish a newer one, choose Update now, and check
   download progress/Cancel while continuing to work. Try declining each close
   question, and an offline/failed download; Spectra must stay open.
7. Accept the Update and verify a progress-only installer, the same installation
   folder, automatic relaunch with the new App version, retained settings and
   the existing taskbar pin. Record whether SmartScreen appeared on this path.

Local validation (2026-10-05, Windows 11, Inno Setup 6.7.3): clean full build;
silent install into a folder with spaces; both shortcut targets and
AppUserModelID; HKCU association/uninstall entry; reinstall without `/DIR`
reused the folder; uninstall removed the app and association while retaining
a user-data marker and both existing QSettings keys byte-for-byte; silent
`/RESTARTAPP=1` started the installed executable. The smoke installation was
then removed. Full suite: 3568 passed, 3 skipped. An initial concurrent-build
run failed the benchmark RAM-peak test; isolated and full reruns passed.
Second-PC permissions, Explorer double-click/icon, taskbar pin survival and
interactive running-app shutdown remain manual checks.
