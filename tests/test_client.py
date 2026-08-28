from flask import Flask, jsonify

from appmanager_sdk import AppManagerClient


def test_client_get_user_from_headers():
    client = AppManagerClient("test-app")
    headers = {
        "X-AppManager-User-Id": "42",
        "X-AppManager-User-Email": "alice@example.com",
        "X-AppManager-User-Role": "admin",
    }
    user = client.get_current_user(headers)
    assert user is not None
    assert user["id"] == 42
    assert user["email"] == "alice@example.com"
    assert user["role"] == "admin"
    assert user["is_admin"] is True


def test_client_require_auth_decorator():
    app = Flask(__name__)
    client = AppManagerClient("test-app")

    @app.route("/protected")
    @client.require_auth(role="admin")
    def protected():
        return jsonify({"secret": "42"})

    with app.test_client() as test_client:
        # Unauthenticated request
        res = test_client.get("/protected")
        assert res.status_code == 302
        assert "/auth/login" in res.location

        # Unauthenticated API request
        res = test_client.get("/protected", headers={"Accept": "application/json"})
        assert res.status_code == 401

        # Insufficient role
        res = test_client.get(
            "/protected",
            headers={
                "Accept": "application/json",
                "X-AppManager-User-Id": "10",
                "X-AppManager-User-Email": "bob@example.com",
                "X-AppManager-User-Role": "user",
            },
        )
        assert res.status_code == 403

        # Authorized admin
        res = test_client.get(
            "/protected",
            headers={
                "X-AppManager-User-Id": "1",
                "X-AppManager-User-Email": "admin@example.com",
                "X-AppManager-User-Role": "admin",
            },
        )
        assert res.status_code == 200
        assert res.get_json() == {"secret": "42"}


def test_client_get_setting_and_slug(monkeypatch):
    client = AppManagerClient()
    assert client._resolve_slug() == "unknown_app"

    monkeypatch.setenv("APPMANAGER_SUBAPP_SLUG", "env-app")
    assert client._resolve_slug() == "env-app"

    # Header takes precedence over env
    assert client._resolve_slug({"X-AppManager-Subapp-Slug": "header-app"}) == "header-app"

    # Setting via environment
    monkeypatch.setenv("APPMANAGER_CONFIG_RATE_LIMIT", "100")
    monkeypatch.setenv("APPMANAGER_CONFIG_FEATURES", '{"dark_mode": true}')
    assert client.get_setting("rate_limit") == 100
    assert client.get_setting("features") == {"dark_mode": True}
    assert client.get_setting("non_existent", default="fallback") == "fallback"


def test_client_graceful_fallbacks():
    client = AppManagerClient("demo-app")
    assert client.report_event("test_event", {"key": "val"}) is False
    assert client.report_metric("latency_ms", 12.5) is False
    assert client.get_data("item", 1) is None
    assert client.set_data("item", 1, {"data": True}) is None
    client.register_slot("sidebar", lambda: None)
    client.register_hook("on_start", lambda: None)


def test_client_functional_helpers():
    from appmanager_sdk import get_current_user, require_auth

    user = get_current_user({"X-AppManager-User-Id": "99", "X-AppManager-User-Role": "admin"})
    assert user is not None and user["id"] == 99

    decorator = require_auth()
    assert callable(decorator)
