"""
AppManager Client SDK.

Provides a lightweight client for sub-apps and extensions running inside or alongside
the AppManager host portal.

The client is deliberately dependency-free at its core: every host integration
(telemetry, storage, settings, hooks) is imported lazily inside the method that
uses it, so the SDK works standalone and only requires the host ``appmanager``
package when those features are actually called.

SECURITY MODEL: identity is conveyed via forwarded ``X-AppManager-User-*`` headers.
This is only safe behind an AppManager gateway that strips incoming headers and
injects its own. An optional shared ``header_secret`` enables HMAC verification of
those headers (see :meth:`AppManagerClient._signature_valid`).
"""

import hashlib
import hmac
import json
import logging
import os
from functools import wraps
from typing import Any, Callable, Dict, Optional, Union

_logger = logging.getLogger(__name__)


class AppManagerClient:
    """
    Lightweight SDK client for sub-applications and extensions.
    Has zero mandatory host dependencies.

    SECURITY: forwarded identity headers (X-AppManager-User-*) are trusted
    verbatim. This client MUST only be used behind an AppManager gateway that
    strips incoming X-AppManager-* headers and injects its own. Never expose
    endpoints protected by @require_auth directly to clients. If a shared
    ``header_secret`` is configured, the gateway must also sign the identity
    context in ``X-AppManager-Signature`` (HMAC-SHA256) and the client will
    reject unsigned/mismatched requests.
    """

    def __init__(
        self,
        app_slug: Optional[str] = None,
        header_secret: Optional[str] = None,
    ) -> None:
        # Resolve the app slug and header secret from explicit args, falling back
        # to environment variables so the client can be configured via env only.
        self.app_slug = app_slug or os.environ.get("APPMANAGER_SUBAPP_SLUG")
        self.header_secret = header_secret or os.environ.get("APPMANAGER_HEADER_SECRET")

    def _signature_valid(self, headers: Any) -> bool:
        """
        Verify HMAC-SHA256 signature over the forwarded identity headers.

        When ``header_secret`` is set, the gateway must sign the identity context
        (``User-Id | User-Email | User-Role``) and send it in
        ``X-AppManager-Signature``. Requests without a valid signature are rejected.
        When no secret is configured, headers are trusted as-is (gateway-only
        deployment) and this always returns True.
        """
        if not self.header_secret:
            return True  # No secret configured -> trust headers (gateway-only deployment).
        provided = headers.get("X-AppManager-Signature") or headers.get(
            "HTTP_X_APPMANAGER_SIGNATURE"
        )
        if not provided:
            return False
        # Build the exact payload the gateway signs: the three identity fields
        # joined by '|'. Both sides must agree on this canonical form.
        payload = "|".join(
            [
                headers.get("X-AppManager-User-Id") or "",
                headers.get("X-AppManager-User-Email") or "",
                headers.get("X-AppManager-User-Role") or "",
            ]
        )
        expected = hmac.new(
            self.header_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        # compare_digest is constant-time, avoiding timing side-channels on the secret.
        return hmac.compare_digest(provided, expected)

    def _resolve_slug(self, headers: Optional[Any] = None) -> str:
        """
        Determine the current app slug.

        Priority: explicit ``app_slug`` > forwarded ``X-AppManager-Subapp-Slug``
        header > ``APPMANAGER_SUBAPP_SLUG`` env var > ``"unknown_app"`` fallback.
        """
        if self.app_slug:
            return self.app_slug
        if headers is None:
            try:
                from flask import request

                headers = request.headers
            except Exception:
                headers = {}
        slug = (
            headers.get("X-AppManager-Subapp-Slug")
            or headers.get("HTTP_X_APPMANAGER_SUBAPP_SLUG")
            or os.environ.get("APPMANAGER_SUBAPP_SLUG", "unknown_app")
        )
        return slug

    def get_current_user(self, headers: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Retrieves the authenticated user forwarded by AppManager via request headers.

        Returns a dict with ``id``, ``email``, ``role``, and ``is_admin``, or None
        when no identity is present (or the signature is invalid).

        SECURITY: trusts forwarded headers. Only safe behind an AppManager gateway
        that strips incoming X-AppManager-* headers. If ``header_secret`` is set,
        requests without a valid ``X-AppManager-Signature`` are rejected.
        """
        if headers is None:
            # No explicit headers -> pull from the active Flask request context.
            try:
                from flask import request

                headers = request.headers
            except Exception:
                headers = {}

        if not self._signature_valid(headers):
            return None

        # Read identity fields, accepting both the raw header name and the
        # WSGI-style ``HTTP_*`` prefixed form for flexibility.
        user_id = headers.get("X-AppManager-User-Id") or headers.get("HTTP_X_APPMANAGER_USER_ID")
        user_email = headers.get("X-AppManager-User-Email") or headers.get(
            "HTTP_X_APPMANAGER_USER_EMAIL"
        )
        user_role = headers.get("X-AppManager-User-Role") or headers.get(
            "HTTP_X_APPMANAGER_USER_ROLE"
        )

        if user_id or user_email:
            return {
                # Coerce numeric ids to int when possible; keep strings otherwise.
                "id": int(user_id) if user_id and str(user_id).isdigit() else user_id,
                "email": user_email,
                "role": user_role or "user",
                "is_admin": (user_role == "admin"),
            }
        return None

    def require_auth(self, role: Optional[str] = None) -> Callable:
        """
        Flask view decorator enforcing authentication and optional role check.

        If ``role`` is specified, users with that role OR the "admin" role are
        allowed; admin users bypass all role checks.

        Unauthenticated API requests get a 401 JSON response; browser requests are
        redirected to the login page. Insufficient-role requests get 403.
        """

        def decorator(f: Callable) -> Callable:
            @wraps(f)
            def decorated_function(*args: Any, **kwargs: Any) -> Any:
                try:
                    from flask import abort, jsonify, redirect, request
                except ImportError:
                    raise RuntimeError("Flask is required to use @require_auth view decorator.")

                user = self.get_current_user(request.headers)
                # Distinguish API vs browser requests to pick the right failure mode.
                is_api = (
                    request.path.startswith("/api/")
                    or request.is_json
                    or "application/json" in request.headers.get("Accept", "")
                )
                if not user:
                    if is_api:
                        return jsonify({"error": "Authentication required"}), 401
                    return redirect("/auth/login?next=" + request.path)

                # Role check: allow the required role OR admin (admins bypass all).
                if role and user.get("role") != role and not user.get("is_admin"):
                    if is_api:
                        return jsonify({"error": "Forbidden - insufficient permissions"}), 403
                    abort(403)

                return f(*args, **kwargs)

            return decorated_function

        return decorator

    def report_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> bool:
        """
        Logs an event to AppManager host telemetry if running inside host environment.

        Returns False (and never raises) when the host bridge is unavailable.
        """
        try:
            from appmanager.bridge import report_event as host_report_event

            slug = self._resolve_slug()
            return bool(host_report_event(slug, event_type, data))
        except Exception:
            return False

    def report_metric(
        self, metric_name: str, value: Union[int, float], unit: Optional[str] = None
    ) -> bool:
        """
        Logs a numeric metric to AppManager host telemetry if running inside host environment.

        Returns False (and never raises) when the host bridge is unavailable.
        """
        try:
            from appmanager.bridge import report_metric as host_report_metric

            slug = self._resolve_slug()
            return bool(host_report_metric(slug, metric_name, value, unit=unit))
        except Exception:
            return False

    def get_data(self, entity_type: str, entity_id: Union[int, str]) -> Optional[Dict[str, Any]]:
        """
        Retrieves JSON data stored by this extension for a specific entity.

        Returns None (and never raises) when the host storage is unavailable.
        """
        try:
            from appmanager.extensions import get_extension_data

            slug = self._resolve_slug()
            result = get_extension_data(slug, entity_type, entity_id)
            return dict(result) if result is not None else None
        except Exception:
            return None

    def set_data(
        self, entity_type: str, entity_id: Union[int, str], data_dict: Optional[Dict[str, Any]]
    ) -> Any:
        """
        Stores or updates JSON data for this extension and entity.

        Returns None (and never raises) when the host storage is unavailable.
        """
        try:
            from appmanager.extensions import set_extension_data

            slug = self._resolve_slug()
            return set_extension_data(slug, entity_type, entity_id, data_dict)
        except Exception:
            return None

    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Retrieves a configured setting value for this app.

        Resolution order:
        1. Environment variable ``APPMANAGER_CONFIG_<KEY>`` (JSON-decoded if possible).
        2. Host ``get_config`` for the installed app record.
        3. The app record's ``settings_json`` blob.
        4. The provided ``default``.

        Failures in the host lookups are logged at debug level and fall through,
        so a broken host integration never crashes the app.
        """
        env_key = f"APPMANAGER_CONFIG_{key.upper()}"
        if env_key in os.environ:
            val = os.environ[env_key]
            try:
                return json.loads(val)
            except Exception:
                return val

        try:
            from appmanager.models import InstalledApp

            slug = self._resolve_slug()
            app_rec = InstalledApp.query.filter_by(slug=slug).first()
            if app_rec:
                try:
                    from appmanager.app_config import get_config

                    val = get_config(app_rec.id, key)
                    if val is not None:
                        return val
                except Exception:
                    _logger.debug(
                        "get_config failed for app %s key %s; falling back to settings_json",
                        slug,
                        key,
                        exc_info=True,
                    )
                if app_rec.settings_json:
                    settings = json.loads(app_rec.settings_json)
                    return settings.get(key, default)
        except Exception:
            _logger.debug("get_setting host lookup failed for key %s", key, exc_info=True)
        return default

    def register_slot(
        self, slot_name: str, callback: Callable[..., Any], priority: int = 10
    ) -> None:
        """
        Registers a UI slot renderer for this sub-app/extension.

        No-op (never raises) when the host hooks module is unavailable.
        """
        try:
            from appmanager.hooks import register_slot

            slug = self._resolve_slug()
            register_slot(slot_name, callback, priority=priority, app_slug=slug)
        except Exception:
            pass

    def register_hook(
        self, hook_name: str, callback: Callable[..., Any], priority: int = 10
    ) -> None:
        """
        Registers a lifecycle hook for this sub-app/extension.

        No-op (never raises) when the host hooks module is unavailable.
        """
        try:
            from appmanager.hooks import register_hook

            slug = self._resolve_slug()
            register_hook(hook_name, callback, priority=priority, app_slug=slug)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Shared database access (approved by admin at install time)
    # ------------------------------------------------------------------

    def get_db_engine(self):
        """
        Returns a SQLAlchemy engine bound to the host's shared database, or None
        when the app was denied DB access (or never requested it).

        Uses the in-process host bridge so raw credentials never reach the app.
        When None, the app should fall back to :meth:`get_local_sqlite`.
        """
        try:
            from appmanager.bridge import get_db_engine as host_get_db_engine

            slug = self._resolve_slug()
            return host_get_db_engine(slug)
        except Exception:
            return None

    def refresh_db_engine(self):
        """
        Disposes any cached engine and re-fetches it from the host (for secret
        rotation or permission changes). Returns the new engine or None.
        """
        try:
            from appmanager.bridge import refresh_db_engine as host_refresh

            slug = self._resolve_slug()
            return host_refresh(slug)
        except Exception:
            return None

    def db_prefix(self) -> str:
        """
        Returns the scoped table prefix for this app (e.g. ``app_weatherapp_``),
        or an empty string when the app has no scoped DB access.
        """
        try:
            from appmanager.bridge import get_db_prefix

            slug = self._resolve_slug()
            return get_db_prefix(slug) or ""
        except Exception:
            return ""

    def db_table(self, name: str) -> str:
        """
        Returns the fully-prefixed table name for this app's scoped namespace
        (e.g. ``client.db_table("users")`` -> ``app_weatherapp_users``).
        """
        prefix = self.db_prefix()
        return f"{prefix}{name}" if prefix else name

    def get_local_sqlite(self, filename: Optional[str] = None):
        """
        Returns a SQLAlchemy engine for an empty local SQLite file owned by this
        app, created on first call. Used as the fallback when shared DB access
        is denied or not requested.

        The file lives under the app's ``instance/`` directory (or the current
        working directory if no instance dir is available).
        """
        import os

        from sqlalchemy import create_engine

        slug = self._resolve_slug()
        filename = filename or f"{slug}.db"
        base = os.getenv("APPMANAGER_INSTANCE_DIR") or os.path.join(
            os.getcwd(), "instance"
        )
        os.makedirs(base, exist_ok=True)
        path = os.path.join(base, filename)
        return create_engine(f"sqlite:///{path}")

    def get_auth_context(self, headers: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """
        Returns a narrow read-only auth context for the current user: login state,
        display name, and role only. Never exposes email, id, or tokens.

        Returns None when the app lacks the ``auth_readonly`` permission or the
        user is not authenticated.
        """
        try:
            from appmanager.bridge import get_auth_context as host_get_auth

            slug = self._resolve_slug()
            res = host_get_auth(slug, headers)
            return res if isinstance(res, dict) else None
        except Exception:
            return None

    def app_api_key(self) -> str:
        """
        Returns the per-app API key injected by the host (via the
        ``X-AppManager-App-Key`` header), or '' when not running under the host.

        The key is injected by the dispatcher middleware, so the app never has to
        store or manage credentials itself.
        """
        try:
            from flask import request

            return request.headers.get("X-AppManager-App-Key") or ""
        except Exception:
            return os.environ.get("APPMANAGER_APP_KEY", "")

    def host_request(
        self,
        method: str,
        path: str,
        json: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Make an authenticated request to the host AppManager REST API using this
        app's per-app API key. ``path`` is relative (e.g. ``/api/v1/health``).

        Returns the parsed JSON response, or raises on HTTP error.
        """
        import json as _json
        import urllib.request

        base = os.environ.get("APPMANAGER_HOST_URL", "http://127.0.0.1:5000")
        url = base.rstrip("/") + "/" + path.lstrip("/")
        req_headers = {
            "X-AppManager-App-Key": self.app_api_key(),
            "X-AppManager-SubApp-Slug": self._resolve_slug(),
            "Content-Type": "application/json",
        }
        if headers:
            req_headers.update(headers)
        data = _json.dumps(json).encode() if json is not None else None
        req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            return _json.loads(body) if body else None


# Convenience singleton instance bound to env config (no explicit args).
client = AppManagerClient()


# Functional helpers for quick imports, mirroring the instance methods.
def get_current_user(headers: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    return client.get_current_user(headers)


def require_auth(role: Optional[str] = None) -> Callable:
    return client.require_auth(role)
