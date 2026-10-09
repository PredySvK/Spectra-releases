# packaging/spectra.spec
# PyInstaller spec for the onedir Spectra.exe (ADR §1.140). Run through
# packaging/build_exe.ps1, never from the development .venv.
#
# Bundled files land under the onedir's _internal/ (sys._MEIPASS); the app reads
# them only through core.asset_paths.resource_path. Qt plugins come from
# PyInstaller's own PySide6 hook.

from pathlib import Path

ROOT = Path(SPECPATH).parent
# The 2048px master art and bytecode caches are not runtime resources.
SKIPPED_DIRS = {"original", "__pycache__"}

datas = [
    (str(path), str(path.parent.relative_to(ROOT)))
    for top in ("resources/icons", "resources/help")
    for path in (ROOT / top).rglob("*")
    if path.is_file() and not SKIPPED_DIRS & set(path.relative_to(ROOT).parts)
]

datas.append((str(ROOT / "benchmark_plan.toml"), "."))
datas.append((str(ROOT / "CHANGELOG.md"), "."))  # Welcome "What's new" + its screenshots
datas += [(str(p), "docs/site/img") for p in (ROOT / "docs/site/img").glob("*.png")]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    excludes=["tkinter", "pytest"],
)
# QtGui's hook also collects optional input/image plugins which Spectra never
# uses. Keep the distribution limited to the desktop widgets and image formats
# we ship; in particular Qt Virtual Keyboard is not an LGPL module.
UNUSED_QT_BINARIES = {
    "qtvirtualkeyboardplugin.dll", "Qt6VirtualKeyboard.dll",
    "qpdf.dll", "Qt6Pdf.dll",
}
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name not in UNUSED_QT_BINARIES]
# The Help window uses QtWebEngine (ADR §1.145). PyInstaller's hook for it also
# pulls QML/Quick/3D, Pdf and the 76 MB devtools paks (+150 MB); the Help view needs
# none of them. Do NOT drop Qt6Quick/Qt6Qml/Qt6OpenGL: Qt6WebEngineCore links them.
WEBENGINE_EXTRAS = ("devtools_resources", ".debug.", "/qml/", "Quick3D", "Qt63D", "Qt6Designer",
                    "VirtualKeyboard", "virtualkeyboard", "Qt6Graphs", "Qt6Charts", "Qt6Location",
                    "Qt6DataVis", "Qt6Multimedia", "Qt6Quick3D", "Qt6Pdf")


def _keep(entry):
    return not any(token in "/" + entry[0].replace("\\", "/") for token in WEBENGINE_EXTRAS)


a.binaries = [entry for entry in a.binaries if _keep(entry)]
a.datas = [entry for entry in a.datas if _keep(entry)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="Spectra",
    icon=str(ROOT / "resources" / "icons" / "app_icon.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Spectra")
