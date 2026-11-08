"""Read-only discovery of saved Markdown notes in an Obsidian vault.

History is derived from files rather than a separate index, so existing notes
remain available after a restart and appending several entries keeps them
together. Hidden files/directories and symbolic links are not included.
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import heapq
import os
from pathlib import Path
import stat
from typing import Any


MAX_NOTE_BYTES = 2 * 1024 * 1024
DEFAULT_HISTORY_LIMIT = 500


@dataclass(frozen=True, slots=True)
class SavedNote:
    """Describe a saved file without reading its body during discovery."""

    path: Path
    modified_ns: int
    size_bytes: int

    @property
    def title(self) -> str:
        return self.path.stem


def _vault_path(config: dict[str, Any]) -> Path:
    vault = Path(os.path.expandvars(os.path.expanduser(
        config["default_vault_path"]))).resolve()
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault directory does not exist: {vault}")
    return vault


def list_notes(config: dict[str, Any],
               limit: int = DEFAULT_HISTORY_LIMIT) -> list[SavedNote]:
    """Return up to ``limit`` visible Markdown files, most recently saved first.

    Only file metadata is read. Directory read failures are reported to the
    caller instead of silently presenting an empty or incomplete history.
    Files removed while scanning are ignored.
    """
    vault = _vault_path(config)
    if limit < 1:
        return []

    def walk_error(error: OSError) -> None:
        raise error

    def candidates():
        for directory, dirs, files, directory_fd in os.fwalk(
                vault, follow_symlinks=False, onerror=walk_error):
            parent = Path(directory)
            dirs[:] = sorted(name for name in dirs
                             if not name.startswith(".")
                             and not (parent / name).is_symlink())
            for name in files:
                path = parent / name
                if name.startswith(".") or path.suffix.casefold() != ".md":
                    continue
                try:
                    metadata = os.stat(name, dir_fd=directory_fd,
                                       follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if stat.S_ISREG(metadata.st_mode):
                    yield SavedNote(path.relative_to(vault),
                                    metadata.st_mtime_ns, metadata.st_size)

    # Keep a bounded result even for large vaults; do not load file bodies.
    return heapq.nsmallest(limit, candidates(),
                          key=lambda note: (-note.modified_ns,
                                            note.path.as_posix().casefold(),
                                            note.path.as_posix()))


def read_note(config: dict[str, Any], note: SavedNote | str | Path,
              max_bytes: int = MAX_NOTE_BYTES) -> str:
    """Read a vault Markdown file, rechecking its location and size.

    Errors propagate so the history page can explain a removed, unreadable,
    oversized, or non-UTF-8 note without changing the current draft.
    """
    vault = _vault_path(config)
    supplied = note.path if isinstance(note, SavedNote) else Path(note)
    candidate = supplied if supplied.is_absolute() else vault / supplied
    resolved = candidate.resolve()
    if not resolved.is_relative_to(vault):
        raise ValueError("History notes must stay inside the configured vault")
    relative = candidate.relative_to(vault)
    if (any(part.startswith(".") for part in relative.parts)
            or candidate.suffix.casefold() != ".md"):
        raise ValueError("History only opens visible Markdown files")
    current = vault
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("History does not open symbolic links")
    if max_bytes < 1:
        raise ValueError("The note size limit must be positive")
    # Hold directory descriptors while walking so a directory replaced with a
    # symlink after validation cannot redirect the read outside the vault.
    with ExitStack() as directories:
        directory_fd = os.open(vault, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directories.callback(os.close, directory_fd)
        for part in relative.parts[:-1]:
            directory_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                   dir_fd=directory_fd)
            directories.callback(os.close, directory_fd)
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("History only opens regular Markdown files")
            data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"Note is too large to preview (limit: {max_bytes:,} bytes)")
    text = data.decode("utf-8-sig")
    if "\x00" in text:
        raise ValueError("Note contains binary data and cannot be previewed")
    return text
