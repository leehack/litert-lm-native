from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import git_lfs_utils


class GitLfsUtilsTest(unittest.TestCase):
    def test_read_pointer_returns_none_for_regular_binary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "library.so"
            path.write_bytes(b"\x7fELF regular library")

            self.assertIsNone(git_lfs_utils.read_git_lfs_pointer(path))

    def test_materializes_verified_object_atomically(self) -> None:
        payload = b"native library payload"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "prebuilt" / "android_arm64" / "library.so"
            path.parent.mkdir(parents=True)
            path.write_text(
                f"version {git_lfs_utils.GIT_LFS_VERSION}\n"
                f"oid sha256:{digest}\n"
                f"size {len(payload)}\n",
                encoding="utf-8",
            )

            def fake_download(url: str, output: Path, **_: object) -> None:
                self.assertEqual(
                    url,
                    "https://media.githubusercontent.com/media/"
                    "google-ai-edge/LiteRT-LM/v0.16.0/"
                    "prebuilt/android_arm64/library.so",
                )
                output.write_bytes(payload)

            with mock.patch.object(
                git_lfs_utils,
                "download_to_path",
                side_effect=fake_download,
            ):
                changed = git_lfs_utils.materialize_git_lfs_file(
                    path,
                    upstream_tag="v0.16.0",
                    source_root=root,
                )

            self.assertTrue(changed)
            self.assertEqual(path.read_bytes(), payload)
            self.assertFalse(path.with_name("library.so.lfs-download").exists())

    def test_checksum_mismatch_preserves_pointer(self) -> None:
        expected = b"expected"
        digest = hashlib.sha256(expected).hexdigest()
        pointer_text = (
            f"version {git_lfs_utils.GIT_LFS_VERSION}\n"
            f"oid sha256:{digest}\n"
            f"size {len(expected)}\n"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "prebuilt" / "linux_x86_64" / "library.so"
            path.parent.mkdir(parents=True)
            path.write_text(pointer_text, encoding="utf-8")

            def fake_download(_: str, output: Path, **__: object) -> None:
                output.write_bytes(b"mismatch")

            with mock.patch.object(
                git_lfs_utils,
                "download_to_path",
                side_effect=fake_download,
            ):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    git_lfs_utils.materialize_git_lfs_file(
                        path,
                        upstream_tag="v0.16.0",
                        source_root=root,
                    )

            self.assertEqual(path.read_text(encoding="utf-8"), pointer_text)

    def test_size_mismatch_preserves_pointer(self) -> None:
        payload = b"payload"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "prebuilt" / "ios_arm64" / "library.dylib"
            path.parent.mkdir(parents=True)
            pointer_text = (
                f"version {git_lfs_utils.GIT_LFS_VERSION}\n"
                f"oid sha256:{digest}\n"
                f"size {len(payload) + 1}\n"
            )
            path.write_text(pointer_text, encoding="utf-8")

            def fake_download(_: str, output: Path, **__: object) -> None:
                output.write_bytes(payload)

            with mock.patch.object(
                git_lfs_utils,
                "download_to_path",
                side_effect=fake_download,
            ):
                with self.assertRaisesRegex(RuntimeError, "size mismatch"):
                    git_lfs_utils.materialize_git_lfs_file(
                        path,
                        upstream_tag="v0.16.0",
                        source_root=root,
                    )

            self.assertEqual(path.read_text(encoding="utf-8"), pointer_text)


if __name__ == "__main__":
    unittest.main()
