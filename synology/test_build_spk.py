"""Offline tests for the Synology SPK layout and installer lifecycle."""
import io
import json
import os
import re
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from build_spk import build


IMAGE = "ghcr.io/floppy69/torrentlinker:sha-012345abcdef"


class SynologySPKTests(unittest.TestCase):
    def test_spk_contains_required_dsm_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "demo.spk"
            build("1.0.0-42", IMAGE, output)
            with tarfile.open(output) as spk:
                names = set(spk.getnames())
                self.assertIn("INFO", names)
                self.assertIn("conf/resource", names)
                self.assertIn("conf/privilege", names)
                self.assertIn("package.tgz", names)
                self.assertEqual(spk.extractfile("PACKAGE_ICON.PNG").read()[1:4], b"PNG")
                info = spk.extractfile("INFO").read().decode()
                self.assertIn('version="1.0.0-42"', info)
                self.assertIn('arch="noarch"', info)
                resource = json.load(spk.extractfile("conf/resource"))
                self.assertEqual(resource["docker-project"]["projects"][0]["name"], "torrentlinker")
                self.assertEqual(json.load(spk.extractfile("conf/privilege"))["defaults"]["run-as"], "package")
                payload = io.BytesIO(spk.extractfile("package.tgz").read())
                with tarfile.open(fileobj=payload, mode="r:gz") as inner:
                    compose = inner.extractfile("project/compose.yaml").read().decode()
                    self.assertIn(IMAGE, compose)
                    self.assertIn('TL_WEB_PASSWORD:', compose)
                    self.assertIn(':/data:ro', compose)

    def test_installer_generates_private_password_and_preserves_it(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            output = folder / "demo.spk"
            build("1.0.0-42", IMAGE, output)
            root = folder / "installed"
            root.mkdir()
            with tarfile.open(output) as spk:
                spk.extractfile("package.tgz", path=folder)
                postinst = spk.extractfile("scripts/postinst").read()
            with tarfile.open(folder / "package.tgz") as inner:
                inner.extractall(root, filter="data")
            script = folder / "postinst.sh"
            script.write_bytes(postinst)
            script.chmod(0o755)
            data = folder / "var"
            env = os.environ | {
                "SYNOPKG_PKGDEST": str(root),
                "SYNOPKG_PKGVAR": str(data),
            }
            subprocess.run(["sh", str(script)], env=env, check=True)
            config = data / "config.env"
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            original = config.read_text()
            self.assertRegex(original, r"TL_WEB_PASSWORD=[a-f0-9]{64}\\n")
            self.assertIn(f"TL_UID={os.getuid()}\n", original)
            self.assertIn(f"TL_GID={os.getgid()}\n", original)
            self.assertEqual((root / "project/.env").read_text(), original)
            subprocess.run(["sh", str(script)], env=env, check=True)
            self.assertEqual(config.read_text(), original)

    def test_rejects_wrong_image_or_version(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "bad.spk"
            with self.assertRaises(ValueError):
                build("1.0.0-beta.25", IMAGE, output)
            with self.assertRaises(ValueError):
                build("1.0.0-2", "ghcr.io/someone/other:latest", output)


if __name__ == "__main__":
    unittest.main()
