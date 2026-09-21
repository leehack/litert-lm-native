from __future__ import annotations

import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import build_upstream_runtime
import windows_dxc
from validate_runtime_artifacts import required_runtime_artifacts


def _fixture_file(member: str, filename: str, payload: bytes) -> windows_dxc.DxcFile:
    return windows_dxc.DxcFile(
        member=member,
        filename=filename,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _archive(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for member, payload in members.items():
            bundle.writestr(member, payload)
    return path


class WindowsDxcTest(unittest.TestCase):
    def test_stages_pinned_runtime_pair_and_licences_only(self) -> None:
        files = (
            _fixture_file("bin/x64/dxil.dll", "dxil.dll", b"dxil"),
            _fixture_file("bin/x64/dxcompiler.dll", "dxcompiler.dll", b"compiler"),
            _fixture_file("LICENSE-MS.txt", "DXC-LICENSE-MS.txt", b"ms terms"),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = _archive(
                root / "dxc.zip",
                {
                    "bin/x64/dxil.dll": b"dxil",
                    "bin/x64/dxcompiler.dll": b"compiler",
                    "bin/arm64/dxil.dll": b"other arch",
                    "bin/x64/dxc.exe": b"tool",
                    "LICENSE-MS.txt": b"ms terms",
                },
            )
            stage_dir = root / "bin" / "windows" / "x64"
            with patch.object(windows_dxc, "DXC_FILES", files):
                self.assertEqual(
                    windows_dxc.extract_dxc_files(archive, stage_dir), len(files)
                )

            self.assertEqual((stage_dir / "dxil.dll").read_bytes(), b"dxil")
            self.assertEqual((stage_dir / "dxcompiler.dll").read_bytes(), b"compiler")
            self.assertEqual(
                (stage_dir / "DXC-LICENSE-MS.txt").read_bytes(), b"ms terms"
            )
            self.assertEqual(
                sorted(path.name for path in stage_dir.iterdir()),
                ["DXC-LICENSE-MS.txt", "dxcompiler.dll", "dxil.dll"],
            )

    def test_rejects_missing_member_without_staging_it(self) -> None:
        files = (_fixture_file("bin/x64/dxil.dll", "dxil.dll", b"dxil"),)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = _archive(root / "dxc.zip", {"bin/x86/dxil.dll": b"dxil"})
            stage_dir = root / "stage"
            with patch.object(windows_dxc, "DXC_FILES", files):
                with self.assertRaisesRegex(RuntimeError, "missing bin/x64/dxil.dll"):
                    windows_dxc.extract_dxc_files(archive, stage_dir)
            self.assertFalse((stage_dir / "dxil.dll").exists())

    def test_rejects_republished_member_checksum(self) -> None:
        files = (_fixture_file("bin/x64/dxil.dll", "dxil.dll", b"pinned"),)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = _archive(root / "dxc.zip", {"bin/x64/dxil.dll": b"republished"})
            stage_dir = root / "stage"
            with patch.object(windows_dxc, "DXC_FILES", files):
                with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                    windows_dxc.extract_dxc_files(archive, stage_dir)
            self.assertFalse((stage_dir / "dxil.dll").exists())

    def test_download_pins_the_official_archive_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            stage_dir = Path(temp) / "stage"
            with patch.object(windows_dxc, "download_to_path") as download, patch.object(
                windows_dxc, "extract_dxc_files", return_value=5
            ) as extract:
                self.assertEqual(windows_dxc.stage_windows_dxc(stage_dir), 5)

            url, archive = download.call_args.args
            self.assertEqual(url, windows_dxc.DXC_ARCHIVE_URL)
            self.assertIn("DirectXShaderCompiler/releases/download/", url)
            self.assertEqual(
                download.call_args.kwargs["expected_sha256"],
                windows_dxc.DXC_ARCHIVE_SHA256,
            )
            self.assertEqual(extract.call_args.args, (archive, stage_dir))
            self.assertFalse(archive.exists())

    def test_windows_staging_adds_dxc_beside_the_upstream_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_dir = root / "source" / "prebuilt" / "windows_x86_64"
            source_dir.mkdir(parents=True)
            (source_dir / "libwebgpu_dawn.dll").write_bytes(b"dawn")
            output = root / "bin"

            with patch.object(build_upstream_runtime, "BIN_DIR", output), patch.object(
                build_upstream_runtime, "stage_windows_dxc"
            ) as stage:
                build_upstream_runtime.stage_windows_runtime_dependencies(
                    root / "source", "x64"
                )

            stage.assert_called_once_with(output / "windows" / "x64")

    def test_release_validation_requires_the_dxc_pair_and_licences(self) -> None:
        for tag, expected in (("v0.16.0", False), ("v0.17.0", True), ("v0.17.1", True)):
            with self.subTest(tag=tag):
                required = {
                    path.as_posix()
                    for path in required_runtime_artifacts(
                        tag, include_official_assets=False
                    )
                }
                self.assertEqual("bin/windows/x64/dxil.dll" in required, expected)
                self.assertEqual(
                    "bin/windows/x64/dxcompiler.dll" in required, expected
                )
        self.assertEqual(
            [path.as_posix() for path in windows_dxc.dxc_license_paths()],
            [
                "bin/windows/x64/DXC-LICENSE-LLVM.txt",
                "bin/windows/x64/DXC-LICENSE-MIT.txt",
                "bin/windows/x64/DXC-LICENSE-MS.txt",
            ],
        )


if __name__ == "__main__":
    unittest.main()
