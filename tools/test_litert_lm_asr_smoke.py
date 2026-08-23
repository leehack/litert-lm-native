from __future__ import annotations

from pathlib import Path
import unittest

from fetch_litert_lm_asr_smoke_assets import ASSETS
from litert_lm_asr_smoke import pinned_asset_sources


class LiteRtLmAsrSmokeTest(unittest.TestCase):
    def test_release_evidence_requires_exact_pinned_asset_names(self) -> None:
        sources = pinned_asset_sources(
            Path(ASSETS[0].filename),
            Path(ASSETS[1].filename),
            Path(ASSETS[2].filename),
        )
        self.assertEqual(sources["model"], ASSETS[0].url)
        self.assertEqual(sources["tokenizer"], ASSETS[1].url)
        self.assertEqual(sources["fixture"], ASSETS[2].url)

        with self.assertRaisesRegex(
            ValueError,
            r"checksum-pinned ASR assets; unsupported input\(s\): model=renamed.tflite",
        ):
            pinned_asset_sources(
                Path("renamed.tflite"),
                Path(ASSETS[1].filename),
                Path(ASSETS[2].filename),
            )


if __name__ == "__main__":
    unittest.main()
