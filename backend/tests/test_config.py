from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if "pydantic_settings" not in sys.modules:
    fake_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover - tiny test shim
        def __init__(self, **kwargs: object) -> None:
            for key, value in kwargs.items():
                setattr(self, key, value)

    fake_module.BaseSettings = BaseSettings
    sys.modules["pydantic_settings"] = fake_module

from app.config import Settings, validate_runtime_settings  # noqa: E402


class ConfigValidationTests(unittest.TestCase):
    def test_production_validation_rejects_default_secrets_and_localhost(self) -> None:
        settings = Settings(
            app_env="production",
            jwt_secret="change-me-in-production",
            encryption_key="change-me-in-production",
            frontend_url="http://localhost:3000",
            google_redirect_uri="http://localhost:8000/api/gmail/callback",
        )

        errors = validate_runtime_settings(settings)

        self.assertIn("jwt_secret must be set to a strong production value", errors)
        self.assertIn("encryption_key must be set to a strong production value", errors)
        self.assertIn("frontend_url cannot point at localhost in production", errors)
        self.assertIn("google_redirect_uri cannot point at localhost in production", errors)

    def test_production_validation_accepts_minimal_safe_settings(self) -> None:
        settings = Settings(
            app_env="production",
            jwt_secret="this-is-a-very-strong-jwt-secret-value",
            encryption_key="this-is-a-very-strong-encryption-key",
            frontend_url="https://app.example.com",
            google_redirect_uri="https://api.example.com/api/gmail/callback",
            document_storage_backend="s3",
            s3_bucket="b-admin",
            s3_endpoint_url="https://example.r2.cloudflarestorage.com",
            s3_access_key_id="abc",
            s3_secret_access_key="def",
        )

        errors = validate_runtime_settings(settings)

        self.assertEqual(errors, [])
