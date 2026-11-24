from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import litert_lm_text_lora_smoke as smoke


class TextLoraSmokeTest(unittest.TestCase):
    def test_abi_only_requires_both_exports_and_exact_values(self) -> None:
        version = "litert_lm_native_text_lora_abi_version"
        supports = "litert_lm_native_supports_text_lora"
        for abi, support, expected in (
            (None, 0, 1), (1, None, 1), (0, 0, 1), (2, 0, 1),
            (1, 1, 1), (1, -1, 1), (1, 0, 0),
        ):
            exports = {
                name: Mock(return_value=value)
                for name, value in ((version, abi), (supports, support))
                if value is not None
            }
            api = SimpleNamespace(library=SimpleNamespace(**exports))
            argv = ["smoke", "--library", "runtime", "--abi-only"]
            with self.subTest(abi=abi, support=support), patch.object(sys, "argv", argv), \
                    patch.object(smoke, "CApi", return_value=api), \
                    redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(smoke.main(), expected)

    def test_real_check_requires_the_setter_trap_and_exact_rejection(self) -> None:
        for setter_error, session, supports, expected in (
            (None, RuntimeError(smoke.SESSION_REJECTION), 0, None),
            (None, RuntimeError(smoke.SESSION_REJECTION), 1, "expected 0"),
            (None, RuntimeError("file unavailable"), 0, "file unavailable"),
            (None, 8, 0, "unexpectedly created"),
            (RuntimeError("setter failed"), RuntimeError(smoke.SESSION_REJECTION), 0,
             "setter failed"),
        ):
            api = Mock()
            api.session_config_create.return_value = 4
            api.engine_create_session.side_effect = [7, session]
            api.session_config_set_lora_path.side_effect = setter_error
            adapter = Path("adapter.tflite")
            with self.subTest(setter_error=setter_error, session=session, supports=supports), \
                    redirect_stdout(io.StringIO()):
                if expected is None:
                    smoke.verify_refusal(api, 2, adapter, supports)
                else:
                    with self.assertRaisesRegex(RuntimeError, expected):
                        smoke.verify_refusal(api, 2, adapter, supports)
            api.session_config_set_lora_path.assert_called_once_with(4, adapter)
            self.assertEqual(api.engine_create_session.call_count, 1 if setter_error else 2)
            api.library.litert_lm_session_delete.assert_any_call(7)
            if session == 8:
                api.library.litert_lm_session_delete.assert_any_call(8)
            api.library.litert_lm_session_config_delete.assert_called_once_with(4)


if __name__ == "__main__":
    unittest.main()
