from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fetch_litert_lm_asr_smoke_assets as assets
import download_utils


class FetchLiteRtLmAsrSmokeAssetsTest(unittest.TestCase):
    def setUp(self):
        def in_process(url, path, **kwargs):
            kwargs["deadline_seconds"] = None
            return download_utils.download_to_path(url, path, **kwargs)

        patched = patch.object(assets, "download_to_path", side_effect=in_process)
        patched.start()
        self.addCleanup(patched.stop)

    def test_downloads_and_reuses_verified_asset(self) -> None:
        payload = b"speech-model"
        asset = assets.Asset(
            filename="model.tflite",
            url="https://example.invalid/model.tflite",
            sha256=hashlib.sha256(payload).hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(
            download_utils.urllib.request, "urlopen", return_value=io.BytesIO(payload)
        ) as urlopen:
            output_dir = Path(temp)
            path = assets.fetch_asset(asset, output_dir)
            self.assertEqual(path.read_bytes(), payload)
            assets.fetch_asset(asset, output_dir)
            urlopen.assert_called_once()

    def test_rejects_checksum_mismatch_without_promoting_partial(self) -> None:
        asset = assets.Asset(
            filename="model.tflite",
            url="https://example.invalid/model.tflite",
            sha256=hashlib.sha256(b"expected").hexdigest(),
        )
        with tempfile.TemporaryDirectory() as temp, patch.object(
            download_utils.urllib.request, "urlopen", return_value=io.BytesIO(b"wrong")
        ):
            output_dir = Path(temp)
            with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                assets.fetch_asset(asset, output_dir)
            self.assertFalse((output_dir / asset.filename).exists())
            self.assertFalse((output_dir / "model.tflite.part").exists())


if __name__ == "__main__":
    unittest.main()
