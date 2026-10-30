"""Offline smoke tests for the native (Docker-free) Synology packaging."""
import io
import os
import struct
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from build_spk import build


class NativeSPK(unittest.TestCase):
    def sample(self, root: Path, machine: int = 62) -> Path:
        runtime = root / "runtime"
        exe = runtime / "bin" / "python3.12"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"\x7fELF\x02\x01" + b"\x00" * 12 + struct.pack("<H", machine))
        exe.chmod(0o755)
        server = runtime / "lib/python3.12/site-packages/torrentlinker/web/server.py"
        server.parent.mkdir(parents=True)
        server.write_text('print("sample")\n')
        return runtime

    def test_native_package_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = self.sample(root)
            out = root / "native.spk"
            build("1.0.0-2", "x86_64", runtime, out)
            with tarfile.open(out) as spk:
                info = spk.extractfile("INFO").read().decode()
                self.assertIn('arch="x86_64"', info)
                self.assertNotIn("ContainerManager", info)
                self.assertEqual(spk.extractfile("conf/resource").read(), b"{}\n")
                self.assertIn('"run-as": "package"', spk.extractfile("conf/privilege").read().decode())
                self.assertEqual(spk.extractfile("PACKAGE_ICON.PNG").read()[:8], b"\x89PNG\r\n\x1a\n")
                payload = io.BytesIO(spk.extractfile("package.tgz").read())
                with tarfile.open(fileobj=payload) as files:
                    self.assertIn("runtime/bin/python3.12", files.getnames())
                    self.assertIn("runtime/lib/python3.12/site-packages/torrentlinker/web/server.py", files.getnames())
                self.assertIn("torrentlinker.web.server", spk.extractfile("scripts/start-stop-status").read().decode())
                self.assertIn("web-password", spk.extractfile("scripts/postinst").read().decode())
                script = root / "postinst"
                script.write_bytes(spk.extractfile("scripts/postinst").read())
                service = root / "service"
                service.write_bytes(spk.extractfile("scripts/start-stop-status").read())
                subprocess.run(["sh", "-n", str(script)], check=True)
                subprocess.run(["sh", "-n", str(service)], check=True)
            env = os.environ | {"SYNOPKG_PKGVAR": str(root / "var"), "SYNOPKG_PKGDEST": str(root)}
            subprocess.run(["sh", str(script)], check=True, env=env)
            password = root / "var/web-password"
            self.assertEqual(len(password.read_text()), 64)
            self.assertEqual(password.stat().st_mode & 0o777, 0o600)
            saved = password.read_text()
            subprocess.run(["sh", str(script)], check=True, env=env)
            self.assertEqual(password.read_text(), saved)
            self.assertEqual(subprocess.run(["sh", str(service), "status"], env=env).returncode, 3)

    def test_arm_architecture_and_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            runtime = self.sample(root, machine=183)
            build("1.0.0-3", "aarch64", runtime, root / "arm.spk")
            with tarfile.open(root / "arm.spk") as archive:
                self.assertIn('arch="armv8"', archive.extractfile("INFO").read().decode())
            with self.assertRaises(ValueError):
                build("1.0.0-3", "x86_64", runtime, root / "bad.spk")
            with self.assertRaises(ValueError):
                build("1.0.0-beta.25", "aarch64", runtime, root / "bad.spk")


if __name__ == "__main__":
    unittest.main()
