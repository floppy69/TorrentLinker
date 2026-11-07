"""Catch Web UI and companion regressions before uploading a Synology SPK."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from synology.tools.audit_web_assets import audit_web_assets


REPO = Path(__file__).resolve().parents[2]


class SynologyWebAssetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="synology-link-audit-")
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name) / "runtime"
        package = self.runtime / "lib/python3.12/site-packages/torrentlinker"
        shutil.copytree(REPO / "src/torrentlinker/web/static", package / "web/static")
        shutil.copytree(REPO / "src/torrentlinker/companion_extension", package / "companion_extension")
        shutil.copytree(REPO / "docs", self.runtime / "share/torrentlinker/docs")

    def test_all_original_ui_links_and_guides_resolve(self) -> None:
        summary = audit_web_assets(self.runtime)
        self.assertEqual(summary["guide_pages"], 32)
        self.assertGreaterEqual(summary["guide_images"], 40)
        self.assertGreaterEqual(summary["static_links"], 17)
        self.assertGreaterEqual(summary["local_markdown_links"], 100)
        self.assertEqual(summary["companion_files"], 8)

    def test_missing_javascript_is_rejected(self) -> None:
        (self.runtime / "lib/python3.12/site-packages/torrentlinker/web/static/app.js").unlink()
        with self.assertRaisesRegex(ValueError, "missing static resource"):
            audit_web_assets(self.runtime)

    def test_missing_guide_image_is_rejected(self) -> None:
        (self.runtime / "share/torrentlinker/docs/guide/images/en/zen.png").unlink()
        with self.assertRaisesRegex(ValueError, "Missing guide image"):
            audit_web_assets(self.runtime)

    def test_missing_companion_module_is_rejected(self) -> None:
        (self.runtime / "lib/python3.12/site-packages/torrentlinker/companion_extension/collect.js").unlink()
        with self.assertRaisesRegex(ValueError, "Missing browser companion files"):
            audit_web_assets(self.runtime)

    def test_missing_documentation_is_rejected(self) -> None:
        (self.runtime / "share/torrentlinker/docs/README.md").unlink()
        with self.assertRaisesRegex(ValueError, "complete French and English"):
            audit_web_assets(self.runtime)


if __name__ == "__main__":
    unittest.main()
