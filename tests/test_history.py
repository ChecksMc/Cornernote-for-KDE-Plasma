"""Saved notes remain discoverable and safe to preview across sessions."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import history
import obsidian


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.config = {"default_vault_path": str(self.vault)}

    def note(self, name, body="Saved note", modified_ns=1):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        os.utime(path, ns=(modified_ns, modified_ns))
        return path

    def test_existing_notes_are_newest_first_with_relative_paths(self):
        self.note("old.md", modified_ns=10)
        self.note("Work/recent.MD", modified_ns=30)
        self.note("middle.md", modified_ns=20)
        notes = history.list_notes(self.config)
        self.assertEqual([note.path.as_posix() for note in notes],
                         ["Work/recent.MD", "middle.md", "old.md"])
        self.assertEqual(notes[0].title, "recent")
        self.assertEqual(notes[0].size_bytes, len(b"Saved note"))

    def test_hidden_files_and_directories_and_non_markdown_are_excluded(self):
        self.note("visible.md")
        self.note(".hidden.md")
        self.note(".obsidian/plugin.md")
        self.note("nested/.trash/deleted.md")
        self.note("image.png")
        self.assertEqual([note.path.as_posix()
                          for note in history.list_notes(self.config)],
                         ["visible.md"])

    def test_symbolic_links_are_not_discovered_or_opened(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "private.md").write_text("Private", encoding="utf-8")
        (self.vault / "linked.md").symlink_to(outside / "private.md")
        (self.vault / "linked-dir").symlink_to(outside, target_is_directory=True)
        self.note("real.md")
        (self.vault / "inside.md").symlink_to(self.vault / "real.md")
        self.assertEqual([note.path.as_posix()
                          for note in history.list_notes(self.config)],
                         ["real.md"])
        for name in ("linked.md", "linked-dir/private.md", "inside.md"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                history.read_note(self.config, name)

    def test_limit_selects_most_recent_and_ties_are_stable(self):
        self.note("b.md", modified_ns=10)
        self.note("a.md", modified_ns=10)
        self.note("newest.md", modified_ns=20)
        notes = history.list_notes(self.config, limit=2)
        self.assertEqual([note.path.as_posix() for note in notes],
                         ["newest.md", "a.md"])

    def test_appended_entries_and_custom_filenames_survive_rediscovery(self):
        self.config["note_filename"] = "{date}-{title}.md"
        path = obsidian.write_note(self.config, "Meeting", "**First entry**",
                                   date_tag="none")
        obsidian.append_to_file(self.config, path.name, "Second entry",
                                date_tag="none")
        notes = history.list_notes(dict(self.config))
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].path, Path("Undated-Meeting.md"))
        body = history.read_note(dict(self.config), notes[0])
        self.assertIn("**First entry**", body)
        self.assertIn("Second entry", body)

    def test_read_errors_do_not_return_empty_content(self):
        self.note("removed.md")
        note = history.list_notes(self.config)[0]
        (self.vault / "removed.md").unlink()
        with self.assertRaises(FileNotFoundError):
            history.read_note(self.config, note)
        self.note("broken.md")
        (self.vault / "broken.md").write_bytes(b"\xff")
        with self.assertRaises(UnicodeError):
            history.read_note(self.config, "broken.md")

    def test_read_is_bounded_even_when_file_grows_after_discovery(self):
        path = self.note("growing.md", "small")
        note = history.list_notes(self.config)[0]
        path.write_text("longer than the limit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "too large"):
            history.read_note(self.config, note, max_bytes=8)

    def test_special_and_binary_files_cannot_block_or_truncate_preview(self):
        os.mkfifo(self.vault / "pipe.md")
        with self.assertRaisesRegex(ValueError, "regular"):
            history.read_note(self.config, "pipe.md")
        self.note("binary.md", "Visible\x00Hidden")
        with self.assertRaisesRegex(ValueError, "binary data"):
            history.read_note(self.config, "binary.md")

    def test_read_rejects_paths_outside_vault_and_hidden_files(self):
        self.note(".hidden.md")
        for name in ("../outside.md", self.root / "outside.md", ".hidden.md"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                history.read_note(self.config, name)

    def test_missing_vault_reports_configuration_error(self):
        self.config["default_vault_path"] = str(self.root / "missing")
        with self.assertRaises(FileNotFoundError):
            history.list_notes(self.config)

    def test_environment_variables_in_vault_path_are_expanded(self):
        self.note("saved.md", "Hello 👋")
        with patch.dict(os.environ, {"CORNERNOTE_TEST_VAULT": str(self.vault)}):
            config = {"default_vault_path": "${CORNERNOTE_TEST_VAULT}"}
            note = history.list_notes(config)[0]
            self.assertEqual(history.read_note(config, note), "Hello 👋")


if __name__ == "__main__":
    unittest.main()
