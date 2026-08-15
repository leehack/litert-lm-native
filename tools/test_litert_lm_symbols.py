from __future__ import annotations

import unittest

from litert_lm_symbols import (
    V0_15_C_API_SYMBOLS,
    V0_16_ASR_BRIDGE_SYMBOLS,
    has_asr_bridge,
    required_bridge_symbols,
    required_c_api_symbols,
    uses_stream_chunk_api,
)


class LiteRtLmSymbolsTest(unittest.TestCase):
    def test_stream_chunk_symbols_start_at_v015(self) -> None:
        v014_symbols = required_c_api_symbols("v0.14.0-native.2")
        v015_symbols = required_c_api_symbols("v0.15.0")

        self.assertTrue(set(V0_15_C_API_SYMBOLS).isdisjoint(v014_symbols))
        self.assertTrue(set(V0_15_C_API_SYMBOLS).issubset(v015_symbols))
        self.assertFalse(uses_stream_chunk_api("v0.14.0-native.2"))
        self.assertTrue(uses_stream_chunk_api("v0.15.0"))

    def test_asr_bridge_symbols_start_at_v016(self) -> None:
        v015_symbols = required_bridge_symbols("v0.15.0-native.3")
        v016_symbols = required_bridge_symbols("v0.16.0")

        self.assertTrue(set(V0_16_ASR_BRIDGE_SYMBOLS).isdisjoint(v015_symbols))
        self.assertTrue(set(V0_16_ASR_BRIDGE_SYMBOLS).issubset(v016_symbols))
        self.assertFalse(has_asr_bridge("v0.15.0-native.3"))
        self.assertTrue(has_asr_bridge("v0.16.0"))


if __name__ == "__main__":
    unittest.main()
