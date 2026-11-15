"""Obsidian vault path selection and append-only Markdown persistence."""

from __future__ import annotations

import datetime as dt
import os
import re
from pathlib import Path
from style import Config

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_date_tag(value: str, base: dt.date | None = None) -> dt.date | None:
    """Parse a compact set of predictable date tags; return None if unknown."""
    if not value or not value.strip():
        return None
    base = base or dt.date.today()
    text = value.strip().lower()
    if text == "today":
        return base
    if text in ("tomorrow", "tmrw"):
        return base + dt.timedelta(days=1)
    match = re.fullmatch(r"in\s+(\d+)\s+days?", text)
    if match:
        return base + dt.timedelta(days=int(match.group(1)))
    weekday = next(
        (i for i, day in enumerate(WEEKDAYS) if text in (day, day + "day")), None
    )
    if weekday is not None:
        offset = (weekday - base.weekday()) % 7 or 7
        return base + dt.timedelta(days=offset)
    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d.%m"):
        try:
            parsed = dt.datetime.strptime(text, fmt).date()
            return parsed.replace(year=base.year) if fmt == "%d.%m" else parsed
        except ValueError:
            continue
    return None


def _safe_filename(template: str, date_text: str, title: str) -> str:
    """Expand supported fields and reject paths or non-Markdown destinations."""
    safe_title = re.sub(r"[^\w -]+", "", title, flags=re.UNICODE).strip()
    safe_title = re.sub(r"\s+", "-", safe_title)[:80] or "QuickNote"
    try:
        filename = template.format(date=date_text, title=safe_title)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid note_filename template: {exc}") from exc
    if not filename.endswith(".md"):
        raise ValueError("note_filename must produce a .md filename")
    if Path(filename).name != filename or filename in (".", ".."):
        raise ValueError("note_filename must be a filename, not a path")
    return filename


def _formatted_date(date_tag: str, date_format: str) -> str | None:
    """Return a formatted note date, or None for the explicit no-date value."""
    if date_tag.strip().casefold() in ("none", "no date"):
        return None
    note_date = parse_date_tag(date_tag) or dt.date.today()
    return note_date.strftime(date_format)


def write_note(
    config: Config, title: str, content: str, date_tag: str = "", folder: str = ""
) -> Path:
    """Append one Markdown entry while preserving drafts on write failures."""
    vault = Path(os.path.expandvars(os.path.expanduser(config["default_vault_path"])))
    if folder and folder != "(root)":
        if Path(folder).name != folder or folder in (".", ".."):
            raise ValueError("Invalid vault folder selection")
        target_dir = vault / folder
        if not target_dir.is_dir():
            raise ValueError(f"Vault folder does not exist: {target_dir}")
    else:
        target_dir = vault
    date_text = _formatted_date(date_tag, config.get("date_format", "%Y-%m-%d"))
    filename = _safe_filename(
        config.get("note_filename", "QuickNotes.md"), date_text or "Undated", title
    )
    path = target_dir / filename
    heading = (
        f"# {date_text}: {title.strip() or 'Quick note'}"
        if date_text
        else f"# {title.strip() or 'Quick note'}"
    )
    body = content.rstrip()
    entry = f"\n{heading}\n{body}\n" if body else f"\n{heading}\n"
    if not target_dir.is_dir():
        raise FileNotFoundError(f"Vault directory does not exist: {target_dir}")
    with path.open("a", encoding="utf-8") as stream:
        stream.write(entry)
        stream.flush()
        os.fsync(stream.fileno())
    return path


def append_to_file(
    config: Config, title_path: str, content: str, date_tag: str = "", folder: str = ""
) -> Path:
    """Append a dated Markdown entry to a file path inside the configured vault."""
    vault = Path(
        os.path.expandvars(os.path.expanduser(config["default_vault_path"]))
    ).resolve()
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault directory does not exist: {vault}")
    base_dir = vault
    if folder and folder != "(root)":
        if Path(folder).name != folder or folder in (".", ".."):
            raise ValueError("Invalid vault folder selection")
        base_dir = (vault / folder).resolve()
        if not base_dir.is_dir() or not base_dir.is_relative_to(vault):
            raise ValueError(
                f"Vault folder does not exist or escapes the vault: {folder}"
            )
    supplied_path = Path(os.path.expandvars(os.path.expanduser(title_path.strip())))
    target = supplied_path if supplied_path.is_absolute() else base_dir / supplied_path
    target = target.resolve()
    if target.suffix.lower() != ".md":
        raise ValueError("Append mode requires a .md filepath in the title field")
    if not supplied_path.is_absolute():
        try:
            target.relative_to(vault)
        except ValueError as exc:
            raise ValueError(
                "Relative append paths must stay inside the configured vault"
            ) from exc
    if not target.parent.is_dir():
        raise FileNotFoundError(f"Parent directory does not exist: {target.parent}")
    date_text = _formatted_date(date_tag, config.get("date_format", "%Y-%m-%d"))
    heading = f"# {date_text}: {target.stem}" if date_text else f"# {target.stem}"
    body = content.rstrip()
    entry = f"\n{heading}\n{body}\n" if body else f"\n{heading}\n"
    with target.open("a", encoding="utf-8") as stream:
        stream.write(entry)
        stream.flush()
        os.fsync(stream.fileno())
    return target
