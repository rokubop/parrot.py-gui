"""Check whether a newer Parrot is on the remote.

`git ls-remote` rather than the GitHub API: it reuses whatever credentials
the checkout already has (the API cannot see a private repo unauthenticated),
has no rate limit, and downloads nothing. It only tells us the remote's sha,
so an exact "N commits behind" is available only when that commit is already
in the local object store from an earlier fetch.

User-triggered only, from a button on the About page. Runs in a QThread: the
network call blocks and the UI must not.
"""
import re
import subprocess

from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

REPO_ROOT = Path(__file__).resolve().parents[2]
FALLBACK_REPO = "rokubop/parrot.py"
GIT_TIMEOUT_S = 20


def _git(*args, timeout=10):
    """Run git in the repo root; None when git or the repo is absent."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), *args],
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _origin_repo():
    """'owner/name' parsed from origin, or the fork this app ships from."""
    url = _git("config", "--get", "remote.origin.url") or ""
    m = re.search(r"github\.com[:/]([^/]+/[^/\s]+?)(?:\.git)?$", url)
    return m.group(1) if m else FALLBACK_REPO


def _default_branch():
    ref = _git("rev-parse", "--abbrev-ref", "origin/HEAD") or "origin/master"
    return ref.split("/", 1)[-1]


def checkout_line():
    """'Checkout <sha> <date>', or None when this is not a git checkout."""
    line = _git("log", "-1", "--format=%h %cs")
    return f"Checkout {line}" if line else None


class UpdateCheckWorker(QThread):
    """Emits a dict: state, repo_url, and behind_by when it can be counted.

    States: up_to_date, behind, ahead, diverged, no_git, error.
    """

    result = pyqtSignal(dict)

    def run(self):
        repo_url = f"https://github.com/{_origin_repo()}"
        head = _git("rev-parse", "HEAD")
        if not head:
            self.result.emit({"state": "no_git", "repo_url": repo_url})
            return

        branch = _default_branch()
        line = _git("ls-remote", "origin", f"refs/heads/{branch}",
                    timeout=GIT_TIMEOUT_S)
        if not line:
            self.result.emit({"state": "error", "repo_url": repo_url})
            return
        remote = line.split()[0]

        if remote == head:
            self.result.emit({"state": "up_to_date", "repo_url": repo_url,
                              "behind_by": 0})
            return

        # Counting needs both commits locally. Without a fetch we may only
        # have ours, which still answers "is there something new".
        counts = _git("rev-list", "--left-right", "--count",
                      f"{head}...{remote}")
        if not counts:
            self.result.emit({"state": "behind", "repo_url": repo_url})
            return
        ahead, behind = (int(n) for n in counts.split())
        state = ("behind" if behind and not ahead else
                 "ahead" if ahead and not behind else "diverged")
        self.result.emit({"state": state, "repo_url": repo_url,
                          "behind_by": behind, "ahead_by": ahead})
