"""Structural SPK tests with a *fake* runtime, never a deployable binary."""

from __future__ import annotations

import io
import json
import struct
import subprocess
import tarfile
import tempfile
import unittest
import zlib
from pathlib import Path

from synology.tools.build_spk import build


def png(size: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0)
    pixels = (b"\x00" + b"\0\0\0\xff" * size) * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


class BuildSpkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.payload = root / "payload"
        python = self.payload / "runtime/bin/python3.12"
        python.parent.mkdir(parents=True)
        elf_header = bytearray(64)
        elf_header[:7] = b"\x7fELF\x02\x01\x01"
        struct.pack_into("<H", elf_header, 18, 62)
        python.write_bytes(elf_header)
        python.chmod(0o755)
        sevenzip = self.payload / "native/bin/7zz"
        sevenzip.parent.mkdir(parents=True)
        sevenzip.write_bytes(elf_header)
        sevenzip.chmod(0o755)
        source = self.payload / "runtime/lib/python3.12/site-packages/torrentlinker/web"
        (source / "static").mkdir(parents=True)
        (source / "server.py").write_text("# fake server in structural test\n")
        (source / "static/index.html").write_text("<!doctype html>\n")
        self.icon64 = root / "icon64.png"
        self.icon256 = root / "icon256.png"
        self.icon64.write_bytes(png(64))
        self.icon256.write_bytes(png(256))
        self.root = root

    def test_spk_structure_and_dsm_metadata(self) -> None:
        output = build(self.payload, self.icon64, self.icon256, self.root / "output")
        with tarfile.open(output, "r") as outer:
            names = set(outer.getnames())
            self.assertEqual(
                names,
                {
                    "INFO", "conf/privilege", "conf/resource",
                    "scripts/preinst", "scripts/postinst",
                    "scripts/preuninst", "scripts/postuninst",
                    "scripts/preupgrade", "scripts/postupgrade",
                    "scripts/start-stop-status",
                    "PACKAGE_ICON.PNG", "PACKAGE_ICON_256.PNG", "package.tgz",
                },
            )
            info = outer.extractfile("INFO").read().decode()
            self.assertIn('arch="x86_64"', info)
            self.assertIn('os_min_ver="7.3-81180"', info)
            self.assertIn('os_max_ver="7.3-99999"', info)
            script = outer.extractfile("scripts/start-stop-status").read().decode()
            self.assertIn('TL_WEB_PORT="8787"', script)
            self.assertIn('--password-file "$SHARED_PASSWORD"', script)
            resource = json.loads(outer.extractfile("conf/resource").read())
            self.assertEqual(
                resource["data-share"]["shares"][0]["name"], "TorrentLinker-Config"
            )
            self.assertEqual(
                resource["data-share"]["shares"][0]["permission"]["rw"],
                ["TorrentLinkerSynology"],
            )
            self.assertEqual(outer.getmember("scripts/start-stop-status").mode, 0o755)
            for name in ("preinst", "postinst", "preuninst", "postuninst", "preupgrade", "postupgrade"):
                self.assertEqual(outer.getmember(f"scripts/{name}").mode, 0o755)
            package_bytes = outer.extractfile("package.tgz").read()
        with tarfile.open(fileobj=io.BytesIO(package_bytes), mode="r:gz") as payload:
            members = set(payload.getnames())
            self.assertIn("runtime/bin/python3.12", members)
            self.assertIn("native/bin/7zz", members)
            self.assertIn(
                "runtime/lib/python3.12/site-packages/torrentlinker/web/static/index.html",
                members,
            )

    def test_reproducible_archive(self) -> None:
        first = build(self.payload, self.icon64, self.icon256, self.root / "one")
        second = build(self.payload, self.icon64, self.icon256, self.root / "two")
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_dsm74_target_has_separate_metadata_and_filename(self) -> None:
        result = build(
            self.payload, self.icon64, self.icon256, self.root / "output",
            target="dsm74-x86_64",
        )
        self.assertEqual(result.name, "TorrentLinkerSynology-1.0.0-0002-dsm74-x86_64.spk")
        with tarfile.open(result, "r") as archive:
            info = archive.extractfile("INFO").read().decode()
        self.assertIn('arch="x86_64"', info)
        self.assertIn('os_min_ver="7.4-90075"', info)
        # There is no artificial ceiling excluding DSM 7.4.1-90080.
        self.assertNotIn("os_max_ver", info)
        self.assertNotIn('os_min_ver="7.3-', info)

    def test_unknown_dsm_target_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported DSM build target"):
            build(
                self.payload, self.icon64, self.icon256, self.root / "output",
                target="noarch",
            )

    def test_missing_python_is_rejected(self) -> None:
        (self.payload / "runtime/bin/python3.12").unlink()
        with self.assertRaisesRegex(ValueError, "Required runtime file missing"):
            build(self.payload, self.icon64, self.icon256, self.root / "output")

    def test_missing_archive_tool_is_rejected(self) -> None:
        (self.payload / "native/bin/7zz").unlink()
        with self.assertRaisesRegex(ValueError, "Required runtime file missing"):
            build(self.payload, self.icon64, self.icon256, self.root / "output")

    def test_non_elf_or_wrong_architecture_is_rejected(self) -> None:
        (self.payload / "runtime/bin/python3.12").write_text("not an ELF\n")
        with self.assertRaisesRegex(ValueError, "x86_64 ELF"):
            build(self.payload, self.icon64, self.icon256, self.root / "output")

    def test_existing_spk_is_not_overwritten(self) -> None:
        build(self.payload, self.icon64, self.icon256, self.root / "output")
        with self.assertRaises(FileExistsError):
            build(self.payload, self.icon64, self.icon256, self.root / "output")

    def test_invalid_icon_is_rejected(self) -> None:
        self.icon64.write_bytes(png(32))
        with self.assertRaisesRegex(ValueError, "64x64"):
            build(self.payload, self.icon64, self.icon256, self.root / "output")

    def test_service_script_has_valid_posix_shell_syntax(self) -> None:
        scripts = Path(__file__).resolve().parents[1] / "package/scripts"
        for script in scripts.iterdir():
            subprocess.run(["sh", "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
