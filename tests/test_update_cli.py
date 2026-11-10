"""Update commands work without a running daemon or loading its settings."""

import contextlib
import importlib.machinery
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
loader = importlib.machinery.SourceFileLoader("corner_note_cli", str(ROOT / "corner-note"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cli = importlib.util.module_from_spec(spec)
loader.exec_module(cli)


class UpdateCliTests(unittest.TestCase):
    def run_command(self, command):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["corner-note", command]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = cli.main()
        return result, output.getvalue(), errors.getvalue()

    def test_check_does_not_install_or_contact_daemon(self):
        from updater import UpdateInfo
        info = UpdateInfo("a" * 40, "b" * 40, "main")
        with patch.object(cli, "check_for_updates", return_value=info), \
                patch.object(cli, "install_update") as install, \
                patch.object(cli, "load_config") as config, \
                patch.object(cli, "send_command") as daemon:
            result, output, errors = self.run_command("check-update")
        self.assertEqual(result, 0)
        self.assertIn("Update available", output)
        self.assertEqual(errors, "")
        install.assert_not_called()
        config.assert_not_called()
        daemon.assert_not_called()

    def test_install_uses_checked_revision_and_explains_restart(self):
        from updater import UpdateInfo
        info = UpdateInfo("a" * 40, "b" * 40, "main")
        with patch.object(cli, "check_for_updates", return_value=info), \
                patch.object(cli, "install_update") as install:
            result, output, _ = self.run_command("update")
        self.assertEqual(result, 0)
        install.assert_called_once_with(info)
        self.assertIn("Save any draft", output)

    def test_up_to_date_does_not_install(self):
        from updater import UpdateInfo
        info = UpdateInfo("a" * 40, "a" * 40, "main")
        with patch.object(cli, "check_for_updates", return_value=info), \
                patch.object(cli, "install_update") as install:
            result, output, _ = self.run_command("update")
        self.assertEqual(result, 0)
        self.assertIn("up to date", output)
        install.assert_not_called()

    def test_failed_update_returns_actionable_error(self):
        with patch.object(cli, "check_for_updates", side_effect=cli.UpdateError("No upstream")):
            result, output, errors = self.run_command("update")
        self.assertEqual(result, 1)
        self.assertEqual(output, "")
        self.assertIn("No upstream", errors)


if __name__ == "__main__":
    unittest.main()
