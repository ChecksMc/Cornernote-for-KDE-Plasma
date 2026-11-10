"""GTK allocation regressions; opt in with CORNERNOTE_GTK_TESTS=1 on a test display."""

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import DEFAULT, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@unittest.skipUnless(os.environ.get("CORNERNOTE_GTK_TESTS") == "1",
                     "requires an isolated GTK test display")
class GtkUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import main
        import style
        if not main.Gtk.init_check()[0]:
            raise unittest.SkipTest("GTK display unavailable")
        cls.app = main
        cls.style = style

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            "CORNERNOTE_CONFIG": str(Path(self.temp.name) / "config.json")})
        self.env.start()
        self.addCleanup(self.env.stop)
        # Broadway exercises GTK's actual size negotiation without requiring a
        # layer-shell compositor or touching the running CornerNote instance.
        layer = patch.multiple(self.app.LayerShell, **dict.fromkeys((
            "init_for_window", "set_namespace", "set_layer", "set_monitor",
            "set_anchor", "set_margin", "set_keyboard_interactivity"), DEFAULT))
        layer.start()
        self.addCleanup(layer.stop)
        self.window = None
        self.addCleanup(self.close_window)

    def close_window(self):
        if self.window is not None:
            self.app.GLib.source_remove(self.window._clock_source)
            for monitor in self.window.theme_monitors:
                monitor.cancel()
            self.window.destroy()
            self.settle()

    def settle(self):
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline:
            while self.app.Gtk.events_pending():
                self.app.Gtk.main_iteration_do(False)
            time.sleep(0.005)

    def make_window(self, **settings):
        config = dict(self.style.DEFAULTS,
                      default_vault_path=self.temp.name,
                      theme_source="fallback")
        config.update(settings)
        self.window = self.app.CornerNote(config)
        self.settle()
        return self.window

    def wait_for(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.settle()
        self.assertTrue(predicate(), "GTK background operation did not complete")

    def test_configured_size_is_independent_of_font_and_page(self):
        for size, width, height in ((8, 380, 340), (28, 380, 340), (28, 240, 180)):
            with self.subTest(font_size=size, width=width, height=height):
                window = self.make_window(font_size=size, width=width, height=height)
                self.assertEqual(tuple(window.get_size()), (width, height))
                window._show_settings()
                window.settings_page.appearance_expander.set_expanded(True)
                self.settle()
                self.assertEqual(tuple(window.get_size()), (width, height))
                window._show_note_page()
                self.settle()
                self.assertEqual(tuple(window.get_size()), (width, height))
                saved = Path(self.temp.name) / "sizing.md"
                saved.write_text("# Saved heading\n**Saved body**")
                window._toggle_history()
                self.wait_for(lambda: not window.history_page.loading)
                self.assertEqual(tuple(window.get_size()), (width, height))
                page = window.history_page
                page.list_box.emit("row-activated", page.list_box.get_children()[0])
                self.wait_for(lambda: not page.reading)
                self.assertEqual(tuple(window.get_size()), (width, height))
                self.close_window()
                self.window = None

    def test_style_changes_restore_size_without_restarting(self):
        window = self.make_window()
        window.resize(700, 600)
        self.settle()
        for font_size in (28, 8, 11):
            window._apply_style_config(dict(window.config, font_size=font_size))
            self.settle()
            self.assertEqual(tuple(window.get_size()), (380, 340))
        window._show_settings()
        window.settings_page.fields["width"].set_value(260)
        window.settings_page.fields["height"].set_value(200)
        self.assertTrue(window._save_settings())
        self.settle()
        self.assertEqual(tuple(window.get_size()), (260, 200))
        self.assertEqual(window.idle_margin(), -192)
        window._apply_style_config(dict(window.config, font_size=28))
        self.settle()
        self.assertEqual(tuple(window.get_size()), (260, 200))

    def test_rendered_formatting_preserves_markdown_and_saves_source(self):
        window = self.make_window()
        source = "# Heading\n**bold** and *italic* and <u>underlined</u>"
        window.title_entry.set_text("Formatting")
        window.content_buffer.set_text(source)
        bold = window.content_buffer.get_tag_table().lookup("md-bold")
        self.assertTrue(window.content_buffer.get_iter_at_offset(source.index("bold")).has_tag(bold))
        window._toggle_preview()
        self.assertEqual(window.body_stack.get_visible_child_name(), "preview")
        preview = window.preview_view.get_buffer()
        self.assertEqual(preview.get_text(*preview.get_bounds(), True),
                         "Heading\nbold and italic and underlined")
        self.assertEqual(window.state.draft.content, source)
        window._toggle_preview()
        self.assertEqual(window.content_buffer.get_text(*window.content_buffer.get_bounds(), True), source)
        window._toggle_preview()
        window.commit_note()
        self.assertIn(source, (Path(self.temp.name) / "QuickNotes.md").read_text())
        self.assertFalse(window.state.draft.has_content())

    def test_settings_validation_and_write_failure_preserve_config_and_draft(self):
        window = self.make_window()
        window.title_entry.set_text("Unsaved title")
        window.content_buffer.set_text("Keep this draft")
        draft = replace(window.state.draft)
        config = dict(window.config)
        window._show_settings()
        page = window.settings_page
        page.fields["width"].set_value(500)
        page.fields["note_filename"].set_text("invalid.txt")
        self.assertFalse(window._save_settings())
        self.assertIn(".md filename", page.status.get_text())
        self.assertFalse(window.config_path.exists())
        self.assertEqual(window.config, config)
        self.assertEqual(window.state.draft, draft)

        page.fields["note_filename"].set_text("valid.md")
        with patch.object(self.app, "save_config", side_effect=OSError("Disk unavailable")):
            self.assertFalse(window._save_settings())
        self.assertIn("Disk unavailable", page.status.get_text())
        self.assertEqual(window.page_stack.get_visible_child_name(), "settings")
        self.assertFalse(window.config_path.exists())
        self.assertEqual(window.config, config)
        self.assertEqual(window.state.draft, draft)
        self.assertEqual(tuple(window.get_size()), (config["width"], config["height"]))

    def test_cancelled_settings_are_reset_when_reopened(self):
        window = self.make_window()
        window.content_buffer.set_text("Keep this draft")
        draft = replace(window.state.draft)
        config = dict(window.config)
        window._toggle_settings()
        fields = window.settings_page.fields
        fields["default_vault_path"].set_text("/another/vault")
        fields["note_filename"].set_text("Another.md")
        fields["width"].set_value(500)
        window._toggle_settings()
        self.assertEqual(window.page_stack.get_visible_child_name(), "note")
        self.assertEqual(window.config, config)
        self.assertEqual(window.state.draft, draft)
        self.assertFalse(window.config_path.exists())

        window._toggle_settings()
        self.assertEqual(fields["default_vault_path"].get_text(), self.temp.name)
        self.assertEqual(fields["note_filename"].get_text(), config["note_filename"])
        self.assertEqual(fields["width"].get_value_as_int(), config["width"])
        self.assertEqual(window.state.draft, draft)

    def test_vault_chooser_cancel_and_accept_preserve_draft_until_settings_save(self):
        selected = Path(self.temp.name) / "selected-vault"
        selected.mkdir()
        window = self.make_window()
        window.pointer_inside = True
        window.content_buffer.set_text("Keep this draft")
        draft = replace(window.state.draft)
        window._show_settings()
        page = window.settings_page
        for result, expected in ((self.app.Gtk.ResponseType.CANCEL, self.temp.name),
                                 (self.app.Gtk.ResponseType.ACCEPT, str(selected))):
            with self.subTest(response=result), \
                    patch.object(self.app.Gtk.FileChooserNative, "new") as create:
                dialog = create.return_value
                dialog.get_filename.return_value = str(selected)
                page.select_vault_button.clicked()
                self.assertTrue(window.file_chooser_open)
                response = dialog.connect.call_args.args[1]
                response(dialog, result)
                dialog.destroy.assert_called_once_with()
                self.assertFalse(window.file_chooser_open)
                self.assertEqual(page.fields["default_vault_path"].get_text(), expected)
                self.assertEqual(window.config["default_vault_path"], self.temp.name)
                self.assertFalse(window.config_path.exists())
                self.assertEqual(window.state.draft, draft)

        self.assertTrue(window._save_settings())
        self.assertEqual(self.style.load_config(window.config_path)["default_vault_path"],
                         str(selected))
        self.assertEqual(window.state.draft, draft)

    def test_vertical_offsets_keep_idle_tab_visible_and_save_clamped_values(self):
        window = self.make_window(height=200, idle_fraction=0.10)
        window._show_settings()
        fields = window.settings_page.fields
        fields["offset_y"].set_value(-1000)
        self.assertEqual(fields["offset_y"].get_value_as_int(), -19)
        fields["height"].set_value(400)
        fields["offset_y"].set_value(-1000)
        self.assertEqual(fields["offset_y"].get_value_as_int(), -39)
        fields["idle_percent"].set_value(5)
        self.assertEqual(fields["offset_y"].get_value_as_int(), -19)

        for position, requested, expected in (("top", -1000, -19),
                                               ("bottom", 1000, 19),
                                               ("center", 1000, 1000)):
            with self.subTest(position=position):
                fields["position_vertical"].set_active_id(position)
                fields["offset_y"].set_value(requested)
                self.assertEqual(fields["offset_y"].get_value_as_int(), expected)
                self.assertTrue(window._save_settings())
                saved = self.style.load_config(window.config_path)
                self.assertEqual(saved["position_vertical"], position)
                self.assertEqual(saved["offset_y"], expected)
                window._show_settings()

    def test_folder_refresh_filters_paths_and_preserves_available_selection(self):
        root = Path(self.temp.name)
        (root / "Work").mkdir()
        (root / "Nested" / "grandchild").mkdir(parents=True)
        (root / "a-note.md").write_text("A file is not a folder")
        window = self.make_window(folders=["Configured", "Nested", ".", "..",
                                           "nested/path", "/absolute"])

        def choices():
            return [row[0] for row in window.folder_combo.get_model()]

        self.assertEqual(choices(), ["(root)", "Configured", "Nested", "Work"])
        window.folder_combo.set_active(3)
        (root / "Added").mkdir()
        window._refresh_folder_choices()
        self.assertEqual(choices(), ["(root)", "Added", "Configured", "Nested", "Work"])
        self.assertEqual(window.folder_combo.get_active_text(), "Work")
        self.assertEqual(window.state.draft.folder, "Work")

        (root / "Work").rmdir()
        window._refresh_folder_choices()
        self.assertEqual(window.folder_combo.get_active_text(), "(root)")
        self.assertEqual(window.state.draft.folder, "(root)")

    def test_toolbar_formats_selected_text_and_returns_from_preview(self):
        window = self.make_window()
        window.content_buffer.set_text("selected")
        window.content_buffer.select_range(*window.content_buffer.get_bounds())
        window._toggle_preview()
        window._format_body(lambda: window._wrap_selection("**"))
        self.assertEqual(window.body_stack.get_visible_child_name(), "edit")
        self.assertEqual(window.content_buffer.get_text(*window.content_buffer.get_bounds(), True),
                         "**selected**")

    def test_failed_save_from_preview_preserves_draft(self):
        window = self.make_window()
        window.title_entry.set_text("Keep this draft")
        window.content_buffer.set_text("**Keep this formatting**")
        window._toggle_preview()
        with patch.object(self.app, "write_note", side_effect=OSError("Disk unavailable")):
            window.commit_note()
        self.assertEqual(window.state.draft.content, "**Keep this formatting**")
        self.assertEqual(window.body_stack.get_visible_child_name(), "preview")
        self.assertIn("Disk unavailable", window.status_label.get_text())

    def test_history_search_and_reading_preserve_unsaved_draft(self):
        root = Path(self.temp.name)
        old = root / "older.md"
        old.write_text("# Older note\n**Saved body**")
        os.utime(old, ns=(1, 1))
        (root / "recent.md").write_text("# Recent note")
        window = self.make_window()
        window.title_entry.set_text("Unsaved title")
        window.content_buffer.set_text("*Unsaved body*")
        window.date_entry.set_text("tomorrow")
        window.state.begin_content()
        window._toggle_preview()
        draft = replace(window.state.draft)
        self.assertTrue(self.app.Gtk.accel_groups_activate(
            window, self.app.Gdk.KEY_h, self.app.Gdk.ModifierType.CONTROL_MASK))
        page = window.history_page
        self.wait_for(lambda: not page.loading)
        rows = page.list_box.get_children()
        self.assertEqual([row.note.path.name for row in rows], ["recent.md", "older.md"])
        page.search_entry.set_text("OLDER")
        self.wait_for(lambda: sum(row.get_child_visible() for row in rows) == 1)
        self.assertTrue(rows[1].get_child_visible())
        page.search_entry.set_text("No match")
        self.wait_for(lambda: "match your search" in page.list_status.get_text())
        page.search_entry.set_text("OLDER")
        self.wait_for(lambda: not page.list_status.get_visible())
        page.list_box.emit("row-activated", rows[1])
        self.wait_for(lambda: not page.reading)
        buffer = page.viewer.get_buffer()
        self.assertEqual(buffer.get_text(*buffer.get_bounds(), True), "Older note\nSaved body")
        self.assertFalse(page.viewer.get_editable())
        window.commit_note()
        window._toggle_date_mode()
        window._toggle_append_mode()
        self.assertEqual(window.state.draft, draft)
        escape = SimpleNamespace(keyval=self.app.Gdk.KEY_Escape, state=0)
        window._on_key(window, escape)
        self.assertEqual(page.stack.get_visible_child_name(), "list")
        window._on_key(window, escape)
        self.assertEqual(window.page_stack.get_visible_child_name(), "note")
        self.assertEqual(window.body_stack.get_visible_child_name(), "preview")
        self.assertEqual(window.state.draft, draft)
        self.assertFalse((root / "QuickNotes.md").exists())

    def test_history_reports_empty_vault_and_removed_note(self):
        window = self.make_window()
        window._toggle_history()
        page = window.history_page
        self.wait_for(lambda: not page.loading)
        self.assertIn("No saved Markdown notes", page.list_status.get_text())
        removed = Path(self.temp.name) / "removed.md"
        removed.write_text("Saved content")
        page.refresh()
        self.wait_for(lambda: not page.loading)
        row = page.list_box.get_children()[0]
        removed.unlink()
        page.list_box.emit("row-activated", row)
        self.wait_for(lambda: not page.reading)
        self.assertIn("Could not open note", page.detail_status.get_text())
        self.assertEqual(page.viewer.get_buffer().get_char_count(), 0)

    def test_history_refresh_ignores_previous_vault_results(self):
        window = self.make_window()
        (Path(self.temp.name) / "previous.md").write_text("Previous")
        window._toggle_history()
        page = window.history_page
        self.wait_for(lambda: not page.loading)
        stale_generation = page._generation
        alternate = Path(self.temp.name) / "alternate"
        alternate.mkdir()
        (alternate / "current.md").write_text("Current")
        page.open(dict(window.config, default_vault_path=str(alternate)))
        self.wait_for(lambda: not page.loading)
        page._finish_loading(stale_generation, [], "Stale error")
        self.assertEqual([row.note.path.name for row in page.list_box.get_children()], ["current.md"])
        self.assertFalse(page.list_status.get_visible())


if __name__ == "__main__":
    unittest.main()
