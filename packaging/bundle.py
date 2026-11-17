#!/usr/bin/env python3
"""Create a clean source archive without repository, cache, docs, or local config."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "CornerNote.zip"
# Only what an installation needs. Documentation media (docs/showcase.gif) is
# deliberately left out; the README links to it on the project page.
INCLUDE = (
    "README.md",
    "LICENSE",
    "config.example.json",
    "corner-note",
    "cornernote.desktop",
    "install.sh",
    "uninstall.sh",
    "src",
    "packaging",
)
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".mypy_cache"}
EXCLUDE_SUFFIXES = {".gif", ".png", ".jpg", ".jpeg", ".webm", ".mp4", ".zip"}


def bundle_files(root: Path = ROOT) -> list[Path]:
    """Return the source files that belong in the distributable archive."""
    files: list[Path] = []
    for entry in INCLUDE:
        source = root / entry
        paths = [source] if source.is_file() else sorted(source.rglob("*"))
        for path in paths:
            if not path.is_file() or any(part in EXCLUDE_DIRS for part in path.parts):
                continue
            if path.name == "config.json" or path.suffix.lower() in EXCLUDE_SUFFIXES:
                continue
            files.append(path)
    return files


def build(output: Path = OUTPUT, root: Path = ROOT) -> Path:
    """Write the archive with a top-level CornerNote directory and return it."""
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in bundle_files(root):
            archive.write(path, Path("CornerNote") / path.relative_to(root))
    return output


def main() -> None:
    """Create the distributable archive from source files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--output", type=Path, default=OUTPUT)
    output = build(parser.parse_args().output.resolve())
    print(f"Created {output}")


if __name__ == "__main__":
    main()
