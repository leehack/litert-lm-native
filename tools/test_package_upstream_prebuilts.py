from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_upstream_prebuilts


class PackageUpstreamPrebuiltsTest(unittest.TestCase):
    def test_materializes_pointer_before_copying_prebuilt(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "source" / "prebuilt" / "android_arm64"
            source_dir.mkdir(parents=True)
            source = source_dir / "libExample.so"
            source.write_text("git-lfs-pointer", encoding="utf-8")
            output = root / "bin"

            def materialize(
                directory: Path,
                *,
                upstream_tag: str,
                source_root: Path,
                suffixes: tuple[str, ...],
            ) -> int:
                self.assertEqual(directory, source_dir)
                self.assertEqual(upstream_tag, "v0.16.0")
                self.assertEqual(source_root, root / "source")
                self.assertIn(".so", suffixes)
                source.write_bytes(b"\x7fELF materialized")
                return 1

            with patch.object(package_upstream_prebuilts, "BIN_DIR", output):
                with patch.object(
                    package_upstream_prebuilts,
                    "PREBUILT_TARGETS",
                    {"android_arm64": ("android", "arm64")},
                ):
                    with patch.object(
                        package_upstream_prebuilts,
                        "materialize_git_lfs_libraries",
                        side_effect=materialize,
                    ):
                        copied = package_upstream_prebuilts.copy_prebuilts(
                            root / "source",
                            upstream_tag="v0.16.0",
                            clean=True,
                        )

            self.assertEqual(copied, 1)
            self.assertEqual(
                (output / "android" / "arm64" / source.name).read_bytes(),
                b"\x7fELF materialized",
            )


if __name__ == "__main__":
    unittest.main()
