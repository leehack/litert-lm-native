from __future__ import annotations

import re
import unittest
from pathlib import Path

from litert_lm_symbols import (
    BRIDGE_SYMBOLS,
    V0_15_C_API_SYMBOLS,
    V0_16_ASR_BRIDGE_SYMBOLS,
    has_asr_bridge,
    required_bridge_symbols,
    required_c_api_symbols,
    uses_stream_chunk_api,
)


class LiteRtLmSymbolsTest(unittest.TestCase):
    def test_v0171_keeps_stream_and_asr_abi_requirements(self) -> None:
        self.assertEqual(required_c_api_symbols("v0.17.1"), required_c_api_symbols("v0.17.0"))
        self.assertEqual(required_bridge_symbols("v0.17.1"), required_bridge_symbols("v0.17.0"))
        self.assertTrue(has_asr_bridge("v0.17.1"))
        self.assertTrue(uses_stream_chunk_api("v0.17.1"))

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

    def test_every_stream_bridge_export_is_required_for_every_tag(self) -> None:
        bridge = (Path(__file__).resolve().parents[1]
                  / "native/bridge/litert_lm_bridge.c").read_text(encoding="utf-8")
        exports = set(re.findall(
            r"^LITERT_LM_BRIDGE_EXPORT [^(]*?\b(\w+)\(", bridge, re.MULTILINE))
        self.assertIn("stream_proxy_finish_reason_abi_version", exports)
        self.assertIn("stream_proxy_get_finish_reason", exports)
        self.assertEqual({symbol.decode() for symbol in BRIDGE_SYMBOLS}, exports)
        for tag in ("v0.15.0", "v0.17.1", "v0.18.0"):
            self.assertTrue(set(BRIDGE_SYMBOLS).issubset(required_bridge_symbols(tag)))


if __name__ == "__main__":
    unittest.main()
