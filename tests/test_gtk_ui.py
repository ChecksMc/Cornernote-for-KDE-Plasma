"""GTK allocation regressions; opt in with CORNERNOTE_GTK_TESTS=1 on a test display."""

import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
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
                      theme_source="fallback", **settings)
        self.window = self.app.CornerNote(config)
        self.settle()
        return self.window

    def test_configured_size_is_independent_of_font_and_page(self):
        for size, width, height in ((8, 380, 340), (28, 380, 340), (28, 240, 180)):
            with self.subTest(font_size=size, width=width, height=height):
                window = self.make_window(font_size=size, width=width, height=height)
                self.assertEqual(tuple(window.get_size()), (width, height))
                window._show_settings()
                window.appearance_expander.set_expanded(True)
                self.settle()
                self.assertEqual(tuple(window.get_size()), (width, height))
                window._show_note_page()
                self.settle()
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
        window.setting_widgets["width"].set_value(260)
        window.setting_widgets["height"].set_value(200)
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


if __name__ == "__main__":
    unittest.main()
