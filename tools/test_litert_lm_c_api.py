from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from litert_lm_c_api import CApi


def api_with(is_v1: bool) -> CApi:
    api = CApi.__new__(CApi)
    api.library = MagicMock()
    api.is_v1 = is_v1
    return api


class CApiTest(unittest.TestCase):
    def test_v1_returns_the_out_parameter_handle(self) -> None:
        api = api_with(True)

        def create(_model, handle) -> int:
            handle._obj.value = 42
            return 0

        api.library.litert_lm_engine_create = create
        self.assertEqual(api._create("litert_lm_engine_create", b"m"), 42)

    def test_v1_failure_reports_status_and_last_error(self) -> None:
        api = api_with(True)
        api.library.litert_lm_engine_create = MagicMock(return_value=3)
        api.library.litert_lm_get_last_error_message.return_value = b"bad model"
        with self.assertRaisesRegex(RuntimeError, r"\(3\): bad model"):
            api._create("litert_lm_engine_create", b"m")

    def test_legacy_returns_the_direct_handle_and_rejects_null(self) -> None:
        api = api_with(False)
        api.library.litert_lm_engine_create = MagicMock(return_value=7)
        self.assertEqual(api._create("litert_lm_engine_create", b"m"), 7)
        api.library.litert_lm_engine_create = MagicMock(return_value=None)
        with self.assertRaisesRegex(RuntimeError, "returned null"):
            api._create("litert_lm_engine_create", b"m")

    def test_legacy_runtime_reports_no_api_version(self) -> None:
        self.assertEqual(api_with(False).api_version(), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
