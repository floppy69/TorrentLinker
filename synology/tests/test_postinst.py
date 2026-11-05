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


if __name__ == "__main__":
    unittest.main()
