from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pydantic_settings" not in sys.modules:
    fake_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - tiny test shim
        def __init__(self, **_: object) -> None:
            pass

    fake_module.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = fake_module

_missing_dependencies: str | None = None

try:
    from fastapi.responses import FileResponse  # noqa: E402
    from app.api.review_ui import REVIEW_UI_PATH, get_reconciliation_review_page  # noqa: E402
except ModuleNotFoundError as exc:  # pragma: no cover - host Python may not have app deps
    _missing_dependencies = str(exc)


if _missing_dependencies:
    class ReviewUiApiTests(unittest.TestCase):
        @unittest.skip(f"review ui tests require app dependencies: {_missing_dependencies}")
        def test_requires_app_dependencies(self) -> None:
            pass
else:
    class ReviewUiApiTests(unittest.IsolatedAsyncioTestCase):
        async def test_returns_review_page_file(self) -> None:
            response = await get_reconciliation_review_page()

            self.assertIsInstance(response, FileResponse)
            self.assertTrue(REVIEW_UI_PATH.exists())
            self.assertTrue(str(response.path).endswith("reconciliation-review.html"))


if __name__ == "__main__":
    unittest.main()
