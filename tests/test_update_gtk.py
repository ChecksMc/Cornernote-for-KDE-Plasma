"""GTK update integration tests; opt in with CORNERNOTE_GTK_TESTS=1 on a test display."""

import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from unittest.mock import DEFAULT, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@unittest.skipUnless(os.environ.get("CORNERNOTE_GTK_TESTS") == "1",
                     "requires an isolated GTK test display")
class GtkUpdateTests(unittest.TestCase):
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

    def test_manual_update_keeps_draft_and_requires_explicit_install(self):
        import update_view
        from updater import UpdateInfo
        window = self.make_window()
        window.title_entry.set_text("Keep my draft")
        window.content_buffer.set_text("**Unfinished**")
        draft = replace(window.state.draft)
        panel = window.update_panel
        info = UpdateInfo("a" * 40, "b" * 40, "main")
        main_thread = threading.get_ident()
        worker_threads = []

        def check():
            worker_threads.append(threading.get_ident())
            return info

        with patch.object(update_view, "check_for_updates", side_effect=check), \
                patch.object(update_view, "install_update") as install:
            panel.check_button.clicked()
            self.wait_for(lambda: not panel.busy)
            install.assert_not_called()
            self.assertTrue(panel.install_button.get_sensitive())
            self.assertIn("Update available", panel.status.get_text())
            panel.install_button.clicked()
            self.wait_for(lambda: not panel.busy)
            install.assert_called_once_with(info)
        self.assertNotEqual(worker_threads, [main_thread])
        self.assertEqual(window.state.draft, draft)
        self.assertTrue(panel.restart_required)
        self.assertIn("Save your draft", panel.status.get_text())
        self.assertFalse(panel.check_button.get_sensitive())
        self.assertFalse(panel.install_button.get_sensitive())

    def test_saved_auto_update_setting_installs_in_background(self):
        import update_view
        from updater import UpdateInfo
        window = self.make_window()
        window.content_buffer.set_text("Keep this text")
        window._show_settings()
        panel = window.update_panel
        self.assertFalse(panel.auto_install.get_active())
        panel.auto_install.set_active(True)
        info = UpdateInfo("a" * 40, "b" * 40, "main")
        with patch.object(update_view, "check_for_updates", return_value=info) as check, \
                patch.object(update_view, "install_update") as install:
            self.assertTrue(window._save_settings())
            self.wait_for(lambda: panel.restart_required)
            check.assert_called_once_with()
            install.assert_called_once_with(info)
        saved = self.style.load_config(window.config_path)
        self.assertIs(saved["auto_update"], True)
        self.assertEqual(window.state.draft.content, "Keep this text")
        panel.configure(False)
        self.assertIsNone(panel._timer)

    def test_unsaved_auto_update_setting_does_not_enable_updates(self):
        import update_view
        window = self.make_window()
        with patch.object(update_view, "check_for_updates") as check:
            window._show_settings()
            window.update_panel.auto_install.set_active(True)
            window._show_note_page()
            self.settle()
            check.assert_not_called()
        self.assertFalse(window.config["auto_update"])
        self.assertIsNone(window.update_panel._timer)

    def test_enabled_setting_checks_at_startup_and_on_timer(self):
        import update_view
        from updater import UpdateInfo
        info = UpdateInfo("a" * 40, "a" * 40, "main")
        with patch.object(update_view, "check_for_updates", return_value=info) as check, \
                patch.object(update_view, "install_update") as install:
            panel = self.make_window(auto_update=True).update_panel
            self.wait_for(lambda: not panel.busy)
            check.assert_called_once_with()
            self.assertIsNotNone(panel._timer)
            panel._automatic_check()
            self.wait_for(lambda: not panel.busy)
            self.assertEqual(check.call_count, 2)
            install.assert_not_called()
        self.assertIn("Up to date", panel.status.get_text())

    def test_disabling_automatic_updates_during_check_prevents_install(self):
        import update_view
        from updater import UpdateInfo
        panel = self.make_window().update_panel
        started, release = threading.Event(), threading.Event()

        def delayed_check():
            started.set()
            release.wait(3)
            return UpdateInfo("a" * 40, "b" * 40, "main")

        with patch.object(update_view, "check_for_updates", side_effect=delayed_check), \
                patch.object(update_view, "install_update") as install:
            try:
                panel.configure(True)
                self.wait_for(started.is_set)
                self.assertTrue(panel.busy)
                panel.configure(False)
                self.assertIsNone(panel._timer)
            finally:
                release.set()
            self.wait_for(lambda: not panel.busy)
            install.assert_not_called()
        self.assertTrue(panel.install_button.get_sensitive())

    def test_update_errors_allow_retry_and_preserve_draft(self):
        import update_view
        from updater import UpdateError, UpdateInfo
        window = self.make_window()
        window.content_buffer.set_text("Preserved draft")
        panel = window.update_panel
        with patch.object(update_view, "check_for_updates", side_effect=UpdateError("Offline")):
            panel.check()
            self.wait_for(lambda: not panel.busy)
        self.assertIn("Offline", panel.status.get_text())
        self.assertTrue(panel.check_button.get_sensitive())
        info = UpdateInfo("a" * 40, "b" * 40, "main")
        with patch.object(update_view, "check_for_updates", return_value=info), \
                patch.object(update_view, "install_update", side_effect=UpdateError("Local changes")):
            panel.check()
            self.wait_for(lambda: not panel.busy)
            panel.install()
            self.wait_for(lambda: not panel.busy)
        self.assertIn("Local changes", panel.status.get_text())
        self.assertTrue(panel.check_button.get_sensitive())
        self.assertFalse(panel.install_button.get_sensitive())
        self.assertFalse(panel.restart_required)
        self.assertEqual(window.state.draft.content, "Preserved draft")


if __name__ == "__main__":
    unittest.main()
