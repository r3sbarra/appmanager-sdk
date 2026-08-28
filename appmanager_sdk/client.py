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


# Convenience singleton instance bound to env config (no explicit args).
client = AppManagerClient()


# Functional helpers for quick imports, mirroring the instance methods.
def get_current_user(headers: Optional[Any] = None) -> Optional[Dict[str, Any]]:
    return client.get_current_user(headers)


def require_auth(role: Optional[str] = None) -> Callable:
    return client.require_auth(role)
