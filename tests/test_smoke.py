"""Headless smoke tests for draft state, note paths, and IPC configuration."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

# The application imports its modules directly from src when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import ipc
import obsidian
import state
import style


class DraftTests(unittest.TestCase):
    def test_set_and_clear_draft_fields(self):
        draft = state.Draft()
        self.assertFalse(draft.has_content())
        draft.title = "Meeting"
        draft.content = "Bring notes"
        draft.date_tag = "tomorrow"
        draft.folder = "Work"
        draft.append_mode = True
        self.assertTrue(draft.has_content())

        draft.clear()
        self.assertEqual(draft, state.Draft())
        self.assertFalse(draft.has_content())

    def test_draft_survives_non_destructive_state_transitions(self):
        # Visibility belongs to the window, not NoteState. Its draft remains in
        # memory until an explicit commit or confirmed discard clears it.
        note = state.NoteState()
        note.draft.title = "Keep me"
        note.draft.content = "Still here"
        note.begin_content()
        self.assertTrue(note.ask_discard())
        note.cancel_discard()
        self.assertEqual(note.mode, state.Mode.CONTENT)
        self.assertEqual((note.draft.title, note.draft.content),
                         ("Keep me", "Still here"))

    def test_confirmed_discard_clears_draft(self):
        note = state.NoteState()
        note.draft.title = "Discard me"
        self.assertTrue(note.ask_discard())
        note.confirm_discard()
        self.assertEqual(note.draft, state.Draft())
        self.assertEqual(note.mode, state.Mode.TITLE)


class ObsidianPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.config = {"default_vault_path": str(self.vault)}

    def test_relative_markdown_path_is_inside_vault(self):
        (self.vault / "work").mkdir()
        path = obsidian.append_to_file(self.config, "work/notes.md", "Hello",
                                       date_tag="none")
        self.assertEqual(path, self.vault / "work" / "notes.md")
        self.assertIn("Hello", path.read_text(encoding="utf-8"))

    def test_relative_path_cannot_escape_vault(self):
        with self.assertRaises(ValueError):
            obsidian.append_to_file(self.config, "../outside.md", "Hello")

    def test_absolute_markdown_path_is_allowed(self):
        target = self.root / "outside.md"
        path = obsidian.append_to_file(self.config, str(target), "Hello",
                                       date_tag="none")
        self.assertEqual(path, target)
        self.assertIn("Hello", target.read_text(encoding="utf-8"))

    def test_append_path_must_be_markdown(self):
        with self.assertRaises(ValueError):
            obsidian.append_to_file(self.config, "notes.txt", "Hello")

    def test_filename_substitutes_date_and_sanitized_title(self):
        self.config["note_filename"] = "{date}-{title}.md"
        path = obsidian.write_note(self.config, "Project / Notes", "Hello",
                                   date_tag="2024-06-15")
        self.assertEqual(path, self.vault / "2024-06-15-Project-Notes.md")
        self.assertIn("Hello", path.read_text(encoding="utf-8"))


class IpcPathTests(unittest.TestCase):
    def test_runtime_dir_resolves_to_socket_used_by_client(self):
        with tempfile.TemporaryDirectory() as runtime_dir:
            config_path = Path(runtime_dir) / "missing-config.json"
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime_dir}):
                config = style.load_config(config_path)
            expected = str(Path(runtime_dir) / "cornernote.sock")
            self.assertEqual(config["socket_path"], expected)
            with patch.object(ipc.socket, "socket") as socket_factory:
                client = socket_factory.return_value.__enter__.return_value
                client.recv.return_value = b"ok\n"
                ipc.send_command(config["socket_path"])
                client.connect.assert_called_once_with(expected)
                client.sendall.assert_called_once_with(b"toggle\n")


class UpdateConfigTests(unittest.TestCase):
    def test_automatic_updates_require_explicit_boolean_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            self.assertIs(style.load_config(path)["auto_update"], False)
            for value in ('"true"', '1', 'null', 'true', 'false'):
                path.write_text('{"auto_update": ' + value + '}')
                self.assertIs(style.load_config(path)["auto_update"], value == 'true')


if __name__ == "__main__":
    unittest.main()
