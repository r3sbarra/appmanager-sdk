"""Tests for security and robustness fixes (2026-08-28 audit squish)."""

import hashlib
import hmac

from appmanager_sdk import AdminSection, AppManifest, Setting
from appmanager_sdk.client import AppManagerClient


def test_secret_default_redacted_in_to_dict():
    """Secret setting defaults must never serialize into manifest.json."""
    manifest = AppManifest(
        name="Payments",
        settings=[Setting(key="stripe_key", type="string", default="sk_live_123", is_secret=True)],
    )
    data = manifest.to_dict()
    assert data["settings_schema"][0]["default"] == "***REDACTED***"
    assert data["settings"]["stripe_key"]["default"] == "***REDACTED***"
    assert "sk_live_123" not in manifest.to_json()


def test_non_secret_default_preserved():
    manifest = AppManifest(name="T", settings=[Setting(key="currency", default="USD")])
    data = manifest.to_dict()
    assert data["settings_schema"][0]["default"] == "USD"


def test_from_dict_ignores_extra_keys():
    """Unknown manifest keys must not crash deserialization (forward-compat)."""
    manifest = AppManifest.from_dict(
        {
            "name": "T",
            "admin_sections": [{"id": "x", "label": "X", "blueprint": "b:bp", "extra": "z"}],
            "scheduled_tasks": [
                {"name": "t", "entry_point": "m:f", "frequency": "daily", "extra": 1}
            ],
        }
    )
    assert len(manifest.admin_sections) == 1
    assert manifest.admin_sections[0].id == "x"
    assert len(manifest.scheduled_tasks) == 1


def test_from_dict_dict_form_preserves_secret_and_label():
    manifest = AppManifest.from_dict(
        {
            "name": "T",
            "settings": {
                "sk": {"type": "string", "default": "x", "is_secret": True, "label": "SK"}
            },
        }
    )
    assert manifest.settings[0].is_secret is True
    assert manifest.settings[0].label == "SK"


def test_validate_catches_bad_type_dup_key_and_blueprint():
    manifest = AppManifest(
        name="T",
        settings=[Setting(key="k", type="bogus"), Setting(key="k", type="string")],
        admin_sections=[AdminSection(id="a", label="A", blueprint="nocolon")],
    )
    errors = manifest.validate()
    assert any("invalid type" in e for e in errors)
    assert any("Duplicate setting key" in e for e in errors)
    assert any("blueprint" in e for e in errors)


def test_validate_extension_requires_target_app():
    manifest = AppManifest(name="T", app_type="extension", target_app=None)
    errors = manifest.validate()
    assert any("target_app" in e for e in errors)


def test_slug_strips_underscores():
    from appmanager_sdk.schema import _sanitize_slug

    assert _sanitize_slug("___test___") == "test"


def test_auth_trusts_headers_without_secret():
    client = AppManagerClient()
    user = client.get_current_user({"X-AppManager-User-Id": "1", "X-AppManager-User-Role": "admin"})
    assert user is not None
    assert user["is_admin"] is True


def test_auth_rejects_unsigned_when_secret_set():
    client = AppManagerClient(header_secret="s3cret")
    user = client.get_current_user({"X-AppManager-User-Id": "1", "X-AppManager-User-Role": "admin"})
    assert user is None


def test_auth_accepts_signed_when_secret_set():
    client = AppManagerClient(header_secret="s3cret")
    headers = {
        "X-AppManager-User-Id": "1",
        "X-AppManager-User-Email": "a@b.com",
        "X-AppManager-User-Role": "admin",
    }
    payload = "|".join(
        [
            headers["X-AppManager-User-Id"],
            headers["X-AppManager-User-Email"],
            headers["X-AppManager-User-Role"],
        ]
    )
    headers["X-AppManager-Signature"] = hmac.new(
        b"s3cret", payload.encode(), hashlib.sha256
    ).hexdigest()
    user = client.get_current_user(headers)
    assert user is not None
    assert user["is_admin"] is True


def test_auth_rejects_tampered_signature():
    client = AppManagerClient(header_secret="s3cret")
    headers = {
        "X-AppManager-User-Id": "1",
        "X-AppManager-User-Email": "a@b.com",
        "X-AppManager-User-Role": "admin",
        "X-AppManager-Signature": "deadbeef",
    }
    assert client.get_current_user(headers) is None
