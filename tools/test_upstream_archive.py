from __future__ import annotations

import unittest

from upstream_archive import github_source_archive_url


class UpstreamArchiveTest(unittest.TestCase):
    def test_stable_tag_uses_documented_tag_archive_endpoint(self) -> None:
        self.assertEqual(
            github_source_archive_url("owner/repo", "v0.16.0"),
            "https://github.com/owner/repo/archive/refs/tags/v0.16.0.tar.gz",
        )

    def test_exact_commit_uses_commit_archive_endpoint(self) -> None:
        commit = "a" * 40
        self.assertEqual(
            github_source_archive_url("owner/repo", commit),
            f"https://github.com/owner/repo/archive/{commit}.tar.gz",
        )

    def test_ambiguous_or_path_bearing_refs_fail_closed(self) -> None:
        for value in ("main", "refs/tags/v0.16.0", "../v0.16.0", "A" * 40):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "exact stable tag"):
                    github_source_archive_url("owner/repo", value)


if __name__ == "__main__":
    unittest.main()
