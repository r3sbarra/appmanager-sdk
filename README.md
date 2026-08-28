# AppManager SDK (`appmanager-sdk`)

[![CI](https://github.com/r3sbarra/appmanager-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/r3sbarra/appmanager-sdk/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/appmanager-sdk.svg)](https://pypi.org/project/appmanager-sdk/)
[![Python Version](https://img.shields.io/pypi/pyversions/appmanager-sdk.svg)](https://pypi.org/project/appmanager-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Lightweight developer SDK, manifest builder, and runtime client for [AppManager Server](https://github.com/r3sbarra/appmanager-server) sub-applications and extensions.

---

## Features

- **No Heavy Host Dependencies**: Zero required external dependencies (pure Python standard library).
- **Python-Native Manifest Definition**: Declare sub-application metadata, settings schema, UI slots, and scheduled tasks directly in your Python entrypoint instead of writing JSON by hand.
- **Automated Manifest Generation**: Export `manifest.json` via CLI (`appmanager-sdk generate` or `appmgr-sdk generate`), python scripts (`manifest.save_manifest()`), or on-demand execution (`python app.py --generate-manifest`).
- **Type-Safe Schema & Autocomplete**: Modern dataclasses (`AppManifest`, `Setting`, `AdminSection`, `ScheduledTask`) with full IDE auto-completion.
- **Runtime Client SDK**: Lightweight `AppManagerClient` with `@require_auth` view decorator, header-based user resolution, and host telemetry integration.
- **Flask Extension Integration**: Clean `AppManager(app, manifest=...)` integration that automatically handles health check routes and CLI commands.

---

## Installation

```bash
pip install appmanager-sdk
```

Optional Flask integration:
```bash
pip install appmanager-sdk[flask]
```

---

## Quick Start

### 1. Define your sub-app and manifest in Python (`app.py`)

```python
from flask import Flask, jsonify, request
from appmanager_sdk import AppManifest, Setting, AdminSection, ScheduledTask, AppManagerClient

app = Flask(__name__)
client = AppManagerClient("analytics-dashboard")

# Define the sub-app manifest directly in Python
manifest = AppManifest(
    name="Analytics Dashboard",
    slug="analytics-dashboard",
    version="1.0.0",
    description="Real-time analytics and visualization sub-app.",
    entry_point="app:app",
    health_check_path="/health",
    has_web_ui=True,
    requires_auth=True,
    settings=[
        Setting(key="api_key", type="string", default="demo-key", description="Ingestion API key"),
        Setting(key="refresh_interval", type="integer", default=60, label="Refresh Rate (s)"),
    ],
    ui_slots=["dashboard_widget"],
    scheduled_tasks=[
        ScheduledTask(name="warm_cache", entry_point="tasks:warm_cache", frequency="hourly")
    ],
)


@app.route("/")
@client.require_auth(role="user")
def index():
    user = client.get_current_user(request.headers)
    api_key = client.get_setting("api_key", default="demo-key")
    return f"<h1>Hello, {user['email'] if user else 'Guest'}</h1><p>API Key: {api_key}</p>"


@app.route("/health")
def health():
    return jsonify({"status": "healthy", "slug": "analytics-dashboard", "version": "1.0.0"})


if __name__ == "__main__":
    import sys

    if "--generate-manifest" in sys.argv or "generate-manifest" in sys.argv:
        manifest.cli()
    else:
        app.run(port=5001, debug=True)
```

---

## 2. Generating `manifest.json`

You have three convenient ways to generate the `manifest.json`:

### Method A: Using the CLI Tool
```bash
# Point to your python entrypoint or module:variable
appmanager-sdk generate app:manifest

# Or generate directly from the python file
appmanager-sdk generate app.py --out manifest.json
```

### Method B: Directly from your script
```bash
python app.py --generate-manifest
```

### Method C: Programmatic Export
```python
manifest.save_manifest("manifest.json")
```

---

## 3. CLI Reference

The `appmanager-sdk` CLI provides essential tools for sub-app developers:

| Command | Description | Example |
| :--- | :--- | :--- |
| `generate [target]` | Generates `manifest.json` from a Python module or file. | `appmanager-sdk generate app:manifest` |
| `validate [file]` | Validates a `manifest.json` or Python manifest against the schema. | `appmanager-sdk validate manifest.json` |
| `init` | Scaffolds a starter Python entrypoint with an `AppManifest`. | `appmanager-sdk init --name "My Service"` |

---

## 4. Manifest Schema Specification

### `AppManifest` Fields

| Field | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `name` | `str` | *required* | Human-readable title of the application. |
| `slug` | `str` | auto-slug | URL-safe slug used for routing (`/apps/<slug>/`). |
| `version` | `str` | `"1.0.0"` | Semantic version string. |
| `description` | `str` | `""` | Short summary of the sub-app purpose. |
| `entry_point` | `str` | `"app:app"` | WSGI callable in `module:callable` format. |
| `health_check_path` | `str` | `"/health"` | Health monitoring route. |
| `app_type` | `str` | `"standalone"` | `"standalone"` (sub-app) or `"extension"` (host modifier). |
| `target_app` | `str` | `None` | Target app slug if `app_type="extension"`. |
| `has_web_ui` | `bool` | `True` | Whether the application exposes a web UI. |
| `requires_auth` | `bool` | `True` | Whether AppManager enforces authentication before dispatching. |
| `settings` | `List[Setting]` | `[]` | List of configurable admin settings. |
| `admin_sections` | `List[AdminSection]` | `[]` | Custom admin panels mounted under `/admin/apps/<slug>/<id>`. |
| `ui_slots` | `List[str]` | `[]` | UI slots this app/extension mounts into (e.g. `user_badge`, `dashboard_widget`). |
| `scheduled_tasks` | `List[ScheduledTask]` | `[]` | Periodic background cron routines. |
| `requests_database` | `bool` | `False` | Request access to the host's shared database. |
| `database_access_level` | `str` | `"scoped"` | `"scoped"` (own table prefix / schema) or `"full"` (raw host DB, trusted only). |
| `database_description` | `str` | `""` | Human-readable description of why the app needs DB access (shown to the admin at approval). |
| `requests_auth_readonly` | `bool` | `False` | Request read-only access to a narrow auth subset (login state, display name, role). |
| `seo` | `SeoInfo` | `None` | Declarative SEO metadata (title, description, keywords, canonical, OG, robots, JSON-LD). |

### `SeoInfo` Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `title` | `str` | Overrides `<title>`; falls back to the manifest `name`. |
| `description` | `str` | Meta description. |
| `keywords` | `list[str]` | Meta keywords. |
| `canonical_url` | `str` | Canonical link href. |
| `og_title` | `str` | Open Graph title. |
| `og_description` | `str` | Open Graph description. |
| `og_image` | `str` | Open Graph image URL. |
| `og_type` | `str` | Open Graph type (e.g. `"website"`). |
| `twitter_card` | `str` | Twitter card type (e.g. `"summary_large_image"`). |
| `twitter_image` | `str` | Twitter image URL. |
| `robots` | `str` | One of `index,follow`, `index,nofollow`, `noindex,follow`, `noindex,nofollow`, `none`. |
| `json_ld` | `dict` | Raw JSON-LD structured data (e.g. `{"@type": "SoftwareApplication"}`). |

All `SeoInfo` fields are optional. The host renders them into the served HTML `<head>` and uses them for `robots.txt` / `sitemap.xml`. Auth-required apps default to `noindex` (configurable in host settings).

**Example:**

```python
manifest = (
    AppManifest(name="Analytics", slug="analytics")
    .with_seo(
        title="Analytics Dashboard",
        description="Real-time analytics for your team.",
        keywords=["analytics", "dashboard"],
        canonical_url="https://example.com/apps/analytics/",
        og_image="https://example.com/og.png",
        robots="index,follow",
        json_ld={"@type": "SoftwareApplication", "name": "Analytics"},
    )
)
```

### `Setting` Types

- `"string"`: Single-line text input
- `"textarea"`: Multi-line text area
- `"integer"`: Number input
- `"boolean"`: Checkbox toggle
- `"color"`: HTML color picker (`#38bdf8`)
- `"json"`: Raw JSON editor / data blob

---

## 5. Flask Extension Pattern

If you prefer the Flask extension pattern:

```python
from flask import Flask
from appmanager_sdk import AppManager

app = Flask(__name__)

mgr = AppManager(
    app,
    name="Payment Service",
    slug="payment-service",
    version="1.0.0",
    description="Processes customer checkouts",
    settings=[{"key": "stripe_key", "type": "string", "label": "Stripe Publishable Key"}],
)

# Automatically adds /health endpoint, attaches app.manifest, and registers Flask CLI commands
```

---

## 6. Runtime Client API (`AppManagerClient`)

When your app runs inside AppManager, the host gateway forwards authenticated user context and config values through request headers:

```python
from appmanager_sdk import AppManagerClient

client = AppManagerClient("my-app")

# User details from gateway headers
user = client.get_current_user(request.headers)
# {"id": 1, "email": "admin@example.com", "role": "admin", "is_admin": True}


# Route protection
@app.route("/admin-only")
@client.require_auth(role="admin")
def admin_route():
    return "Admin area"


# Config / Setting retrieval
api_key = client.get_setting("api_key", default="fallback")

# Extension storage
client.set_data("user", user_id, {"flair": "VIP"})
data = client.get_data("user", user_id)

# Host telemetry
client.report_event("checkout_completed", {"amount": 49.99})
client.report_metric("response_time_ms", 12.4, unit="ms")
```

---

## 7. Shared Database Access

An app can request access to the host's shared database by setting
`requests_database=True` in its manifest. On install, the admin approves or
denies the request (default is **deny**).

- **Approved (scoped)** — the app gets its own table prefix (`app_<slug>_`) or
  dedicated MySQL schema. Use `client.db_table("users")` to get a namespaced
  table name.
- **Approved (full)** — the app gets a raw engine to the host DB. Only approve
  for apps you trust completely.
- **Denied** — `get_db_engine()` returns `None`; the app should fall back to
  `get_local_sqlite()`.

```python
# In your app, when running under the host:
engine = client.get_db_engine()          # SQLAlchemy engine or None if denied
if engine is None:
    engine = client.get_local_sqlite()    # empty local SQLite fallback

# Scoped table naming (only meaningful when scoped access is granted):
table = client.db_table("users")          # e.g. "app_myapp_users"
```

> **Security**: the engine is handed to your app in-process by the host bridge.
> Credentials never exist as strings in your app's memory, and are never sent
> over the network or written to files.

## 8. Read-Only Auth Access

An app can request read-only access to a narrow auth subset by setting
`requests_auth_readonly=True` in its manifest. When approved, `get_auth_context()`
returns only **login state, display name, and role** — never email, user id,
passwords, or tokens.

```python
ctx = client.get_auth_context(request.headers)
# {"authenticated": True, "display_name": "Alice", "role": "admin"}  or None
if ctx and ctx["authenticated"]:
    greeting = f"Hello, {ctx['display_name']}!"
```

## 9. Per-App API Key & Host API Calls

Each installed app gets a per-app API key, generated by the host on install and
injected into the request context. Use it to authenticate service-to-service
calls back to the host REST API — no credentials to store or manage.

```python
# The key is injected by the host; you never see or store it.
key = client.app_api_key()

# Make an authenticated call to the host REST API:
result = client.host_request("GET", "/api/v1/health")
```

---

## Security

### Forwarded identity headers (trust model)

`get_current_user()` and `@require_auth` trust the `X-AppManager-User-*` headers
forwarded by the AppManager gateway. **This is only safe behind a gateway that
strips incoming `X-AppManager-*` headers and injects its own.** Never expose
endpoints protected by `@require_auth` directly to clients.

To defend against a misconfigured proxy that fails to strip forged headers, you
can require a shared-secret HMAC signature on the identity context:

```python
client = AppManagerClient("my-app", header_secret="<shared-secret>")
# or via env: APPMANAGER_HEADER_SECRET
```

When `header_secret` is set, the gateway must sign the identity context
(`User-Id | User-Email | User-Role`) with HMAC-SHA256 and send it in
`X-AppManager-Signature`. Requests without a valid signature are rejected.

### Manifest generation executes code

`appmanager-sdk generate` and `load_manifest_from_module()` **execute the target
Python file** to discover the manifest declaration. Only run them on code you
trust — never on untrusted input (e.g. unvetted PRs in CI).

---

## License

MIT License. See [LICENSE](LICENSE) for details.
