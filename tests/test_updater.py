"""Exercise update discovery and loss-free installation with local Git remotes."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import updater


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        self.publisher = self.root / "publisher"
        self.checkout = self.root / "cornernote"
        self.git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.git(self.root, "init", "--initial-branch=main", str(self.publisher))
        (self.publisher / "app.py").write_text("initial version\n")
        self.git(self.publisher, "add", "app.py")
        self.git(self.publisher, "commit", "-m", "Initial version")
        self.git(self.publisher, "remote", "add", "origin", str(self.remote))
        self.git(self.publisher, "push", "-u", "origin", "main")
        self.git(self.root, "clone", str(self.remote), str(self.checkout))
        self.initial_revision = self.git(self.checkout, "rev-parse", "HEAD")

    @staticmethod
    def git(directory, *args):
        result = subprocess.run(
            ["git", "-c", "user.name=CornerNote Tests",
             "-c", "user.email=cornernote-tests@example.invalid",
             "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
            cwd=directory, check=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()

    def publish(self, content="updated version\n"):
        (self.publisher / "app.py").write_text(content)
        self.git(self.publisher, "commit", "-am", "Publish update")
        self.git(self.publisher, "push", "origin", "HEAD")
        return self.git(self.publisher, "rev-parse", "HEAD")

    def test_current_checkout_has_no_update(self):
        info = updater.check_for_updates(self.checkout)
        self.assertFalse(info.available)
        self.assertEqual(info.current_revision, self.initial_revision)
        self.assertEqual(info.target_revision, self.initial_revision)
        self.assertEqual(info.branch, "main")

    def test_check_fetches_without_installing(self):
        target = self.publish()
        info = updater.check_for_updates(self.checkout)
        self.assertTrue(info.available)
        self.assertEqual(info.current_revision, self.initial_revision)
        self.assertEqual(info.target_revision, target)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)
        self.assertEqual((self.checkout / "app.py").read_text(), "initial version\n")

    def test_install_fast_forwards_and_preserves_settings_and_notes(self):
        config = self.root / "config.json"
        config.write_text('{"auto_update": true}')
        vault = self.root / "vault"
        vault.mkdir()
        note = vault / "Notes.md"
        note.write_text("My existing note\n")
        target = self.publish()
        updater.install_update(updater.check_for_updates(self.checkout), self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), target)
        self.assertEqual((self.checkout / "app.py").read_text(), "updated version\n")
        self.assertEqual(config.read_text(), '{"auto_update": true}')
        self.assertEqual(note.read_text(), "My existing note\n")

    def test_install_uses_checked_commit_even_if_remote_advances(self):
        target = self.publish("first update\n")
        info = updater.check_for_updates(self.checkout)
        self.publish("later update\n")
        self.git(self.checkout, "fetch", "origin")
        updater.install_update(info, self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), target)
        self.assertEqual((self.checkout / "app.py").read_text(), "first update\n")

    def test_check_ignores_concurrent_fetch_head_changes_and_cleans_private_ref(self):
        target = self.publish()
        run_git = updater._git
        interleaved = []

        def interleave_fetch(root, *args, **kwargs):
            result = run_git(root, *args, **kwargs)
            if args[0] == "fetch":
                # Another Git user fetches after the updater's fetch completes,
                # replacing the shared FETCH_HEAD before its target is read.
                self.git(self.checkout, "fetch", "--quiet", "origin", self.initial_revision)
                interleaved.append(True)
            return result

        with patch.object(updater, "_git", side_effect=interleave_fetch):
            info = updater.check_for_updates(self.checkout)
        self.assertTrue(interleaved)
        self.assertEqual(info.target_revision, target)
        self.assertEqual(self.git(self.checkout, "rev-parse", "FETCH_HEAD"), self.initial_revision)
        self.assertEqual(self.git(self.checkout, "for-each-ref", "refs/cornernote/"), "")

    def test_branch_merge_options_cannot_squash_instead_of_updating_head(self):
        target = self.publish()
        info = updater.check_for_updates(self.checkout)
        self.git(self.checkout, "config", "branch.main.mergeOptions", "--squash")
        updater.install_update(info, self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), target)
        self.assertEqual(self.git(self.checkout, "status", "--porcelain"), "")

    def test_dirty_tracked_file_is_not_overwritten(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        local = self.checkout / "app.py"
        local.write_text("My local edits\n")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertEqual(local.read_text(), "My local edits\n")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_staged_file_is_not_overwritten(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        (self.checkout / "app.py").write_text("Staged changes\n")
        self.git(self.checkout, "add", "app.py")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertIn("Staged changes", self.git(self.checkout, "show", ":app.py"))
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_untracked_file_is_preserved_and_blocks_install(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        local = self.checkout / "local-notes.md"
        local.write_text("Uncommitted notes\n")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertEqual(local.read_text(), "Uncommitted notes\n")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_ignored_file_newly_tracked_upstream_is_not_overwritten(self):
        local = self.checkout / "config.json"
        local.write_text("My private configuration\n")
        (self.checkout / ".git" / "info" / "exclude").write_text("config.json\n")
        (self.publisher / "config.json").write_text("Upstream configuration\n")
        self.git(self.publisher, "add", "config.json")
        self.git(self.publisher, "commit", "-m", "Start tracking configuration")
        self.git(self.publisher, "push", "origin", "main")
        self.assertEqual(self.git(self.checkout, "status", "--porcelain"), "")
        info = updater.check_for_updates(self.checkout)
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertEqual(local.read_text(), "My private configuration\n")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_autostash_configuration_cannot_hide_dirty_files(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        self.git(self.checkout, "config", "merge.autoStash", "true")
        local = self.checkout / "app.py"
        local.write_text("My local edits\n")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertEqual(local.read_text(), "My local edits\n")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)
        self.assertEqual(self.git(self.checkout, "stash", "list"), "")

    def test_local_commit_ahead_of_remote_is_not_downgraded(self):
        (self.checkout / "app.py").write_text("Local commit\n")
        self.git(self.checkout, "commit", "-am", "Local commit")
        local_head = self.git(self.checkout, "rev-parse", "HEAD")
        with self.assertRaises(updater.UpdateError):
            updater.check_for_updates(self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), local_head)

    def test_diverged_branch_is_not_merged(self):
        self.publish()
        (self.checkout / "app.py").write_text("Diverging local commit\n")
        self.git(self.checkout, "commit", "-am", "Diverging local commit")
        local_head = self.git(self.checkout, "rev-parse", "HEAD")
        with self.assertRaises(updater.UpdateError):
            updater.check_for_updates(self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), local_head)
        self.assertFalse((self.checkout / ".git" / "MERGE_HEAD").exists())

    def test_detached_head_is_unsupported(self):
        self.git(self.checkout, "checkout", "--detach")
        with self.assertRaises(updater.UpdateError):
            updater.check_for_updates(self.checkout)

    def test_missing_upstream_is_unsupported(self):
        self.git(self.checkout, "branch", "--unset-upstream")
        with self.assertRaises(updater.UpdateError):
            updater.check_for_updates(self.checkout)

    def test_archive_directory_is_unsupported(self):
        archive = self.root / "archive"
        archive.mkdir()
        with self.assertRaises(updater.UpdateError):
            updater.check_for_updates(archive)

    def test_parent_repository_cannot_be_mistaken_for_installation(self):
        nested = self.checkout / "extracted-cornernote"
        nested.mkdir()
        with self.assertRaises(updater.UpdateError):
            updater.check_for_updates(nested)

    def test_configured_upstream_branch_is_used(self):
        self.git(self.publisher, "checkout", "-b", "release")
        self.git(self.publisher, "push", "-u", "origin", "release")
        self.git(self.checkout, "fetch", "origin")
        self.git(self.checkout, "checkout", "--track", "origin/release")
        target = self.publish("release branch update\n")
        info = updater.check_for_updates(self.checkout)
        self.assertEqual(info.branch, "release")
        self.assertEqual(info.target_revision, target)
        updater.install_update(info, self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), target)

    def test_changed_head_invalidates_checked_update(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        (self.checkout / "local.txt").write_text("Local commit\n")
        self.git(self.checkout, "add", "local.txt")
        self.git(self.checkout, "commit", "-m", "Local commit after check")
        local_head = self.git(self.checkout, "rev-parse", "HEAD")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), local_head)

    def test_changed_branch_invalidates_checked_update(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        self.git(self.checkout, "checkout", "-b", "other")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertEqual(self.git(self.checkout, "branch", "--show-current"), "other")
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_changed_upstream_invalidates_checked_update(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        self.git(self.checkout, "config", "branch.main.merge", "refs/heads/other")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_pending_merge_blocks_install(self):
        self.publish()
        info = updater.check_for_updates(self.checkout)
        pending = self.checkout / ".git" / "MERGE_HEAD"
        pending.write_text(info.target_revision + "\n")
        with self.assertRaises(updater.UpdateError):
            updater.install_update(info, self.checkout)
        self.assertTrue(pending.exists())
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_fetch_failure_reports_update_error(self):
        self.git(self.checkout, "remote", "set-url", "origin", str(self.root / "missing.git"))
        with self.assertRaises(updater.UpdateError):
            updater.check_for_updates(self.checkout)
        self.assertEqual(self.git(self.checkout, "rev-parse", "HEAD"), self.initial_revision)

    def test_subprocess_timeout_is_reported_as_update_error(self):
        with patch.object(updater.subprocess, "run",
                          side_effect=subprocess.TimeoutExpired("git", 1)):
            with self.assertRaises(updater.UpdateError):
                updater.check_for_updates(self.checkout)

    def test_missing_git_is_reported_as_update_error(self):
        with patch.object(updater.subprocess, "run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(updater.UpdateError):
                updater.check_for_updates(self.checkout)


if __name__ == "__main__":
    unittest.main()
