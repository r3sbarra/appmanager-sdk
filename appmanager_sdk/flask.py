"""
Flask Extension Integration for AppManager.

Provides seamless integration between Flask applications and AppManager manifests and SDK.

The :class:`AppManager` extension binds a manifest and client to a Flask app, registers
a health-check endpoint, and exposes a ``flask manifest generate`` CLI command. Each app
keeps its own manifest in its extension registry, so one AppManager instance can
initialize multiple apps with distinct manifests.
"""

from typing import Any, Dict, Optional, Union

from appmanager_sdk.client import AppManagerClient
from appmanager_sdk.schema import AppManifest


class AppManager:
    """
    Flask Extension that binds an AppManifest and AppManagerClient to a Flask application.

    Example:
        app = Flask(__name__)
        mgr = AppManager(
            app,
            name="Analytics Sub-App",
            slug="analytics",
            version="1.0.0",
            health_check_path="/health"
        )

    The manifest can be supplied as an :class:`AppManifest`, a dict, or keyword
    arguments (``name``, ``slug``, etc.).
    """

    def __init__(
        self,
        app: Optional[Any] = None,
        manifest: Optional[Union[AppManifest, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> None:
        self.manifest: Optional[AppManifest] = None
        self.client: Optional[AppManagerClient] = None

        # Resolve the manifest from an explicit object, a dict, or kwargs.
        if manifest is not None:
            if isinstance(manifest, AppManifest):
                self.manifest = manifest
            elif isinstance(manifest, dict):
                self.manifest = AppManifest.from_dict(manifest)
        elif kwargs:
            self.manifest = AppManifest(**kwargs)

        # If an app was passed, initialize it immediately.
        if app is not None:
            self.init_app(app)

    def init_app(
        self, app: Any, manifest: Optional[Union[AppManifest, Dict[str, Any]]] = None
    ) -> None:
        """
        Initializes the Flask application with AppManager extension hooks.

        ``manifest`` may be passed to attach a specific manifest to this app;
        otherwise the instance-level manifest (or a fallback from the app name)
        is used. Each app keeps its own manifest in its extension registry, so
        one AppManager can initialize multiple apps with distinct manifests.
        """
        # Allow an explicit per-app manifest override; otherwise reuse the
        # instance-level manifest or fall back to one derived from the app name.
        if manifest is not None:
            if isinstance(manifest, AppManifest):
                self.manifest = manifest
            elif isinstance(manifest, dict):
                self.manifest = AppManifest.from_dict(manifest)
        elif self.manifest is None:
            # Fallback default manifest from app name
            self.manifest = AppManifest(name=getattr(app, "name", "Sub-App"))

        self.client = AppManagerClient(app_slug=self.manifest.slug)

        # Attach the manifest and client to the app instance via multiple
        # conventions so both the generator and consumers can find them.
        app.manifest = self.manifest
        app.__appmanager_manifest__ = self.manifest
        if not hasattr(app, "extensions"):
            app.extensions = {}
        app.extensions["appmanager"] = self
        app.extensions["appmanager_manifest"] = self.manifest
        app.extensions["appmanager_client"] = self.client

        # Register health check endpoint if not already handled.
        health_path = self.manifest.health_check_path or "/health"
        existing_endpoints = [rule.rule for rule in app.url_map.iter_rules()]
        if health_path not in existing_endpoints:
            from flask import jsonify

            # Read the manifest from THIS app's extension registry so reusing
            # one AppManager on multiple apps reports the correct slug/version.
            def _health_view() -> Any:
                manifest = app.extensions.get("appmanager_manifest") or self.manifest
                if manifest is None:
                    return jsonify({"status": "unhealthy", "error": "no manifest"}), 500
                return jsonify(
                    {
                        "status": "healthy",
                        "app_slug": manifest.slug,
                        "version": manifest.version,
                    }
                )

            app.add_url_rule(health_path, endpoint="appmanager_health", view_func=_health_view)

        # Register a ``flask manifest generate`` CLI command if Flask CLI is active.
        try:
            import click

            @app.cli.group("manifest")
            def manifest_cli():
                """AppManager manifest operations."""
                pass

            @manifest_cli.command("generate")
            @click.option(
                "--out", "-o", default="manifest.json", help="Output path for manifest.json"
            )
            def generate_command(out: str) -> None:
                """Generates manifest.json from this Flask application."""
                manifest = self.manifest
                if manifest is None:
                    click.echo("✗ No manifest configured on this AppManager.", err=True)
                    return
                saved = manifest.save_manifest(out)
                click.echo(f"✓ Generated manifest at: {saved}")

        except Exception:
            # Flask CLI may be unavailable (e.g. no click installed); skip gracefully.
            pass

    def add_setting(
        self,
        key: str,
        type: str = "string",
        label: Optional[str] = None,
        default: Any = None,
        description: Optional[str] = None,
        is_secret: bool = False,
    ) -> "AppManager":
        """Fluent builder: add a setting to the bound manifest and return self."""
        if self.manifest:
            self.manifest.add_setting(
                key=key,
                type=type,
                label=label,
                default=default,
                description=description,
                is_secret=is_secret,
            )
        return self
