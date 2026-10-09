"""Collect runtime dependency notices from the clean build environment."""

from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys

from packaging.requirements import Requirement


def write_third_party_licenses(destination: Path) -> None:
    """Copy wheel license files, metadata notices and the Python license."""
    root = Path(__file__).resolve().parent.parent
    destination.mkdir(parents=True, exist_ok=True)
    pending = [
        Requirement(line.split("#", 1)[0].strip()).name
        for line in (root / "requirements.txt").read_text().splitlines()
        if line.split("#", 1)[0].strip()
    ]
    seen = set()
    while pending:
        package = distribution(pending.pop())
        name = package.metadata["Name"]
        if name in seen:
            continue
        seen.add(name)
        folder = destination / f"{name}-{package.version}"
        folder.mkdir(exist_ok=True)
        # METADATA also carries inline licenses and attribution which older
        # wheels do not expose as separate license files.
        (folder / "METADATA.txt").write_text(package.read_text("METADATA"), encoding="utf-8")
        for entry in package.files or ():
            if any("license" in part.lower() or "copying" in part.lower()
                   or "notice" in part.lower() for part in entry.parts):
                source = Path(package.locate_file(entry))
                if source.is_file():
                    target = folder.joinpath(*(part if part != ".." else "_parent"
                                               for part in entry.parts))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
        for dependency in package.requires or ():
            requirement = Requirement(dependency)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    shutil.copyfile(Path(sys.base_prefix) / "LICENSE.txt", destination / "Python-LICENSE.txt")
    shutil.copytree(root / "packaging" / "licenses", destination / "Qt", dirs_exist_ok=True)


if __name__ == "__main__":
    write_third_party_licenses(Path(sys.argv[1]))
