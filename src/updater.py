"""Safe, fast-forward-only updates for CornerNote source checkouts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GIT_TIMEOUT = 60


class UpdateError(RuntimeError):
    """An update could not be checked or safely installed."""


@dataclass(frozen=True)
class UpdateInfo:
    """A checked upstream revision and the checkout it can update."""

    current_revision: str
    target_revision: str
    branch: str
    upstream: str = ""
    remote: str = ""
    merge_ref: str = ""

    @property
    def available(self) -> bool:
        """Whether the checked upstream contains a newer revision."""
        return self.current_revision != self.target_revision


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a bounded Git command without opening authentication prompts."""
    environment = os.environ.copy()
    environment.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/false",
        "SSH_ASKPASS": "/bin/false",
        "LC_ALL": "C",
    })
    environment.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes -oConnectTimeout=15")
    try:
        result = subprocess.run(
            ["git", "-c", "submodule.recurse=false", *args],
            cwd=root, env=environment, capture_output=True, text=True,
            timeout=GIT_TIMEOUT, check=False,
        )
    except FileNotFoundError as exc:
        raise UpdateError("Git is required for updates. Install Git and try again.") from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError("The update operation timed out. Check your connection and try again.") from exc
    except OSError as exc:
        raise UpdateError(f"Could not run Git: {exc}") from exc
    if check and result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise UpdateError(detail[-800:] or "Git could not complete the update operation.")
    return result


def _repository(project_dir: str | Path) -> Path:
    """Reject archives and directories inside an unrelated parent repository."""
    root = Path(project_dir).expanduser().resolve()
    if not root.is_dir():
        raise UpdateError("The CornerNote source directory is missing.")
    result = _git(root, "rev-parse", "--show-toplevel", check=False)
    if result.returncode or Path(result.stdout.strip()).resolve() != root:
        raise UpdateError(
            "Updates require a Git checkout of CornerNote. "
            "For an archive installation, download the latest source and run install.sh again."
        )
    return root


def _checkout(root: Path) -> tuple[str, str, str, str, str]:
    """Read the branch, HEAD, and configured upstream without assuming origin/main."""
    result = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
    if result.returncode:
        raise UpdateError("Updates require a checked-out branch; this checkout has a detached HEAD.")
    branch = result.stdout.strip()
    current = _git(root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    remote = _git(root, "config", "--get", f"branch.{branch}.remote", check=False).stdout.strip()
    merge_ref = _git(root, "config", "--get", f"branch.{branch}.merge", check=False).stdout.strip()
    if not remote or not merge_ref:
        raise UpdateError("This branch has no upstream. Configure a tracking branch before checking for updates.")
    if (not merge_ref.startswith("refs/heads/")
            or _git(root, "check-ref-format", merge_ref, check=False).returncode):
        raise UpdateError("The configured upstream must be a single Git branch.")
    upstream = f"{remote}/{merge_ref.removeprefix('refs/heads/')}"
    return branch, current, upstream, remote, merge_ref


def _require_idle(root: Path) -> None:
    """Avoid changing a checkout involved in another Git operation."""
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge",
                 "rebase-apply", "sequencer", "BISECT_LOG"):
        location = _git(root, "rev-parse", "--git-path", name).stdout.strip()
        if (root / location).exists():
            raise UpdateError("Finish the pending Git operation before updating CornerNote.")


def _require_fast_forward(root: Path, current: str, target: str) -> None:
    if current == target:
        return
    result = _git(root, "merge-base", "--is-ancestor", current, target, check=False)
    if result.returncode == 0:
        return
    if result.returncode != 1:
        raise UpdateError("Could not compare update revisions. Check your Git history and try again.")
    result = _git(root, "merge-base", "--is-ancestor", target, current, check=False)
    if result.returncode == 0:
        raise UpdateError("This checkout is ahead of its upstream. Updates will not replace local commits.")
    raise UpdateError("This checkout has diverged from its upstream. Resolve the Git history before updating.")


def check_for_updates(project_dir: str | Path = PROJECT_ROOT) -> UpdateInfo:
    """Fetch the current branch's upstream and inspect a possible fast-forward."""
    root = _repository(project_dir)
    _require_idle(root)
    branch, current, upstream, remote, merge_ref = _checkout(root)
    temporary_ref = f"refs/cornernote/update-{uuid.uuid4().hex}"
    try:
        try:
            _git(root, "fetch", "--quiet", "--no-tags", "--no-recurse-submodules",
                 "--no-write-fetch-head", "--", remote,
                 f"{merge_ref}:{temporary_ref}")
        except UpdateError as exc:
            raise UpdateError(f"Could not fetch updates: {exc}") from exc
        target = _git(root, "rev-parse", "--verify", f"{temporary_ref}^{{commit}}").stdout.strip()
    finally:
        # A private ref prevents another fetch from replacing this check's
        # target. Remove it after obtaining the immutable commit identifier.
        try:
            _git(root, "update-ref", "-d", temporary_ref, check=False)
        except UpdateError:
            pass
    _require_fast_forward(root, current, target)
    return UpdateInfo(current, target, branch, upstream, remote, merge_ref)


def install_update(info: UpdateInfo, project_dir: str | Path = PROJECT_ROOT) -> None:
    """Install the exact checked commit without discarding local changes."""
    root = _repository(project_dir)
    _require_idle(root)
    branch, current, upstream, remote, merge_ref = _checkout(root)
    if (branch, current, upstream, remote, merge_ref) != (
            info.branch, info.current_revision, info.upstream, info.remote, info.merge_ref):
        raise UpdateError("The checkout or upstream changed. Check for updates again before installing.")
    if not all(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", revision)
               for revision in (info.current_revision, info.target_revision)):
        raise UpdateError("The checked update revision is invalid. Check for updates again.")
    if _git(root, "status", "--porcelain", "--untracked-files=all",
            "--ignore-submodules=none").stdout:
        raise UpdateError("Local changes or untracked files are present. Commit or move them before updating.")
    _require_fast_forward(root, current, info.target_revision)
    if not info.available:
        return
    _git(root, "-c", f"branch.{branch}.mergeOptions=", "-c", "core.hooksPath=/dev/null",
         "merge", "--ff-only", "--no-edit", "--no-autostash",
         "--no-overwrite-ignore", "--", info.target_revision)
    installed = _git(root, "rev-parse", "--verify", "HEAD^{commit}").stdout.strip()
    if installed != info.target_revision:
        raise UpdateError("Git did not activate the checked update. Check the checkout before trying again.")
