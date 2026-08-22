from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import package_release


UPSTREAM_COMMIT = "924e79c91542761242244e4f1651851f822e4cbb"
NATIVE_COMMIT = "451ba0ce7c366972b4dc0e58f08ffe590958f943"


class PackageReleaseTest(unittest.TestCase):
    def test_manifest_separates_all_release_identities_and_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            library = bin_dir / "linux" / "x64" / "libLiteRtLm.so"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"runtime")
            evidence_dir = root / "evidence"
            evidence_dir.mkdir()
            (evidence_dir / "linux-x64.json").write_text(
                json.dumps(
                    {
                        "id": "litert_lm_asr_moonshine",
                        "result": "pass",
                        "platform": "linux",
                        "arch": "x64",
                        "upstreamCommit": UPSTREAM_COMMIT,
                        "nativeCommit": NATIVE_COMMIT,
                        "backend": "cpu",
                        "abiVersion": 1,
                        "library": {"sha256": "1" * 64},
                        "model": {"sha256": "2" * 64},
                        "tokenizer": {"sha256": "3" * 64},
                        "fixture": {"sha256": "4" * 64},
                        "transcript": "how are you doing",
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(package_release, "REPO_ROOT", root),
                patch.object(package_release, "BIN_DIR", bin_dir),
                patch.object(package_release, "WEB_DIST_DIR", root / "web"),
                patch.object(package_release, "DIST_DIR", root / "dist"),
                patch.object(package_release, "SHA256SUMS_PATH", root / "SHA256SUMS"),
            ):
                manifest = package_release.build_manifest(
                    upstream_tag="v0.16.0",
                    upstream_commit=UPSTREAM_COMMIT,
                    compatibility_tag="v0.16.0",
                    release_tag="v0.16.0-3",
                    native_commit=NATIVE_COMMIT,
                    evidence_dir=evidence_dir,
                    official_upstream_assets=True,
                )

        self.assertEqual(manifest["schemaVersion"], 2)
        self.assertEqual(manifest["release"]["tag"], "v0.16.0-3")
        self.assertEqual(manifest["upstream"]["tag"], "v0.16.0")
        self.assertEqual(manifest["upstream"]["commit"], UPSTREAM_COMMIT)
        self.assertEqual(manifest["native"]["commit"], NATIVE_COMMIT)
        self.assertEqual(manifest["abi"]["asrBridge"], 1)
        self.assertEqual(manifest["platforms"][0]["platform"], "linux")
        self.assertEqual(
            manifest["platforms"][0]["releaseAsset"],
            "litert-lm-native-runtime-linux-x64-v0.16.0-3.tar.gz",
        )
        self.assertEqual(len(manifest["realModelSmokes"]), 1)
        self.assertEqual(
            manifest["artifacts"][0]["sha256"],
            "d92c6a81b2ff50096bcda80885427d1f59a25b5f483f7055523504925d16ab23",
        )

    def test_evidence_must_match_exact_source_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            evidence_dir = Path(temp)
            (evidence_dir / "bad.json").write_text(
                json.dumps(
                    {
                        "id": "litert_lm_asr_moonshine",
                        "result": "pass",
                        "platform": "linux",
                        "arch": "x64",
                        "upstreamCommit": "0" * 40,
                        "nativeCommit": NATIVE_COMMIT,
                        "backend": "cpu",
                        "abiVersion": 1,
                        "library": {"sha256": "1" * 64},
                        "model": {"sha256": "2" * 64},
                        "tokenizer": {"sha256": "3" * 64},
                        "fixture": {"sha256": "4" * 64},
                        "transcript": "how are you doing",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "upstream commit mismatch"):
                package_release.load_smoke_evidence(
                    evidence_dir,
                    upstream_commit=UPSTREAM_COMMIT,
                    native_commit=NATIVE_COMMIT,
                )


if __name__ == "__main__":
    unittest.main()
