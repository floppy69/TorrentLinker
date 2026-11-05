"""Contract tests for the read-only upstream source policy."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from synology.tools.check_upstream_integrity import check


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.STDOUT,
    ).strip()


class SourceIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.name", "Synology CI")
        git(self.repo, "config", "user.email", "ci@example.invalid")
        (self.repo / "src").mkdir()
        (self.repo / "src" / "app.py").write_text("VERSION = 1\n", encoding="utf-8")
        git(self.repo, "add", "src/app.py")
        git(self.repo, "commit", "-qm", "original project")
        baseline = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "synology").mkdir()
        (self.repo / "synology" / "upstream.sha").write_text(
            baseline + "\n", encoding="utf-8"
        )
        (self.repo / "synology" / "README.md").write_text("packaging\n", encoding="utf-8")
        git(self.repo, "add", "synology")
        git(self.repo, "commit", "-qm", "add Synology files")

    def commit(self, path: str, contents: str) -> None:
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(contents, encoding="utf-8")
        git(self.repo, "add", path)
        git(self.repo, "commit", "-qm", f"change {path}")

    def test_new_synology_files_are_accepted(self) -> None:
        self.assertEqual(check(self.repo), [])

    def test_native_spk_workflow_is_allowed(self) -> None:
        self.commit(".github/workflows/synology-dsm73-build.yml", "name: build\n")
        self.assertEqual(check(self.repo), [])

    def test_original_file_modification_is_rejected(self) -> None:
        self.commit("src/app.py", "VERSION = 2\n")
        self.assertIn("Upstream file changed or removed: src/app.py", check(self.repo))

    def test_new_file_outside_synology_is_rejected(self) -> None:
        self.commit("README.md", "unauthorized new file\n")
        self.assertIn("New file outside Synology allowlist: README.md", check(self.repo))

    def test_uncommitted_changes_are_rejected_when_requested(self) -> None:
        (self.repo / "src" / "app.py").write_text("VERSION = 2\n", encoding="utf-8")
        self.assertEqual(check(self.repo), [])
        self.assertIn(
            "Working tree contains modified or untracked files",
            check(self.repo, check_worktree=True),
        )


if __name__ == "__main__":
    unittest.main()
