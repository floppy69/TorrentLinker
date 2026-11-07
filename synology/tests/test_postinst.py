"""Native DSM installation hooks must provision private credentials safely."""

from __future__ import annotations

import os
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

POSTINST = Path(__file__).resolve().parents[1] / "package/scripts/postinst"
SERVICE = Path(__file__).resolve().parents[1] / "package/scripts/start-stop-status"


class NativeInstallTests(unittest.TestCase):
    def test_password_generation_and_upgrade_preservation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synology-postinst-") as folder:
            env = dict(os.environ, SYNOPKG_PKGVAR=folder)
            first = subprocess.run(
                ["sh", str(POSTINST)], env=env, check=True, capture_output=True, text=True
            )
            self.assertEqual(first.stdout, "")
            self.assertEqual(first.stderr, "")
            path = Path(folder) / "secrets/web-password"
            first_secret = path.read_text(encoding="utf-8").strip()
            self.assertRegex(first_secret, r"^[0-9a-f]{48}$")
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            subprocess.run(["sh", str(POSTINST)], env=env, check=True)
            self.assertEqual(path.read_text(encoding="utf-8").strip(), first_secret)

    def test_shared_password_initialization_and_admin_change(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synology-share-") as folder:
            root = Path(folder)
            private = root / "var"
            share = root / "TorrentLinker-Config"
            share.mkdir()
            env = dict(os.environ, SYNOPKG_PKGVAR=str(private), TL_SYNOLOGY_SHARE_DIR=str(share))
            subprocess.run(["sh", str(POSTINST)], env=env, check=True)

            initial = (private / "secrets/web-password").read_text(encoding="utf-8")
            shared = share / "web-password.txt"
            result = subprocess.run(
                ["sh", str(SERVICE), "prepare-password"],
                env=env, check=True, capture_output=True, text=True,
            )
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "")
            self.assertEqual(shared.read_text(encoding="utf-8"), initial)
            self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o600)

            # DSM/File Station administrator edits the shared file. The next
            # package start must use it without silently reverting to the seed.
            shared.write_text("my-updated-secure-password\n", encoding="utf-8")
            subprocess.run(["sh", str(SERVICE), "prepare-password"], env=env, check=True)
            self.assertEqual(shared.read_text(encoding="utf-8"), "my-updated-secure-password\n")
            self.assertEqual((private / "secrets/web-password").read_text(), initial)

    def test_missing_share_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synology-no-share-") as folder:
            root = Path(folder)
            env = dict(
                os.environ, SYNOPKG_PKGVAR=str(root / "var"),
                TL_SYNOLOGY_SHARE_DIR=str(root / "not-created"),
            )
            subprocess.run(["sh", str(POSTINST)], env=env, check=True)
            result = subprocess.run(
                ["sh", str(SERVICE), "prepare-password"],
                env=env, capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing Synology shared folder", result.stderr)

    def test_invalid_or_symlinked_password_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="synology-invalid-password-") as folder:
            root = Path(folder)
            private = root / "var"
            share = root / "share"
            share.mkdir()
            env = dict(os.environ, SYNOPKG_PKGVAR=str(private), TL_SYNOLOGY_SHARE_DIR=str(share))
            subprocess.run(["sh", str(POSTINST)], env=env, check=True)
            shared = share / "web-password.txt"
            shared.write_text("weak\n", encoding="utf-8")
            result = subprocess.run(
                ["sh", str(SERVICE), "prepare-password"], env=env,
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Invalid Web password", result.stderr)
            shared.unlink()
            shared.symlink_to(private / "secrets/web-password")
            result = subprocess.run(
                ["sh", str(SERVICE), "prepare-password"], env=env,
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing a symlink", result.stderr)


if __name__ == "__main__":
    unittest.main()
