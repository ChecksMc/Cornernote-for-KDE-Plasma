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


if __name__ == "__main__":
    unittest.main()
