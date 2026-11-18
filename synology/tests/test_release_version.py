"""Release tag to DSM package version contract."""
import unittest
from synology.tools.release_version import from_tag


class VersionTests(unittest.TestCase):
    def test_prerelease_increments(self):
        self.assertEqual(from_tag("v1.0.0-beta.43"), "1.0.0-3043")
        self.assertLess(from_tag("v1.0.0-beta.43"), from_tag("v1.0.0-beta.44"))

    def test_pre_stable_order(self):
        tags = ["v1.0.0-alpha.1", "v1.0.0-beta.43", "v1.0.0-rc.1", "v1.0.0"]
        versions = [from_tag(tag) for tag in tags]
        self.assertEqual(versions, sorted(versions))
        self.assertEqual(versions[-1], "1.0.0-9000")

    def test_reject_unexpected(self):
        for value in ("v1.0.0-b.1", "v1.0.0-beta.1000", "nightly",
                      "v1.0.0-beta.01", "v1.0.0+local"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                from_tag(value)


if __name__ == "__main__":
    unittest.main()
