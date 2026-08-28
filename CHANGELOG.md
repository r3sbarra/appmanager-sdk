# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **SEO metadata**: new `SeoInfo` dataclass and `AppManifest.seo` field. Apps can
  declare `title`, `description`, `keywords`, `canonical_url`, Open Graph
  (`og_title`/`og_description`/`og_image`/`og_type`), Twitter card
  (`twitter_card`/`twitter_image`), `robots`, and `json_ld` structured data.
  Added fluent `AppManifest.with_seo(**kwargs)` builder. Wired into
  `to_dict`/`from_dict`/`validate` (robots allowlist + json_ld type check).
  Exported `SeoInfo` from the package root.

### Security
- **Secret redaction**: `Setting.to_dict()` and `AppManifest.to_dict()` now redact
  `default` values for `is_secret=True` settings, so real secrets never serialize
  into `manifest.json`.
- **Auth header verification**: `AppManagerClient` now supports an optional
  `header_secret` (env `APPMANAGER_HEADER_SECRET`). When set, forwarded identity
  headers must carry a valid `X-AppManager-Signature` (HMAC-SHA256) or the request
  is rejected. Documented the gateway-only trust model.
- **CLI init injection**: `appmanager-sdk init` now sanitizes the slug and escapes
  the name as a Python string literal (and HTML-escapes it for the generated page),
  closing a code-injection vector via `--name`/`--slug`.

### Fixed
- **`sys.path` pollution**: `load_manifest_from_module()` now restores `sys.path`
  after execution via a context manager.
- **`from_dict()` forward-compat**: `AdminSection`/`ScheduledTask` now use explicit
  field extraction instead of `**kwargs`, so unknown manifest keys no longer crash.
- **Dict-form settings metadata**: `from_dict()` now preserves `is_secret` and
  `label` when reading the `settings` dict form.
- **Flask multi-app health slug**: `init_app()` captures the manifest at init time,
  so reusing an `AppManager` on another app reports the correct slug/version.
- **`validate()` gaps**: now checks setting types, duplicate setting keys,
  `AdminSection` blueprint format, `ScheduledTask` frequency, and extension
  `target_app` requirement.
- **Slug sanitization**: `_sanitize_slug()` now also strips leading/trailing
  underscores.

### Changed
- **Version single-sourced**: `pyproject.toml` now reads the version from
  `appmanager_sdk.__version__` (PEP 621 `dynamic`).
- **License**: added `LICENSE` file; `pyproject.toml` uses SPDX `license = "MIT"`
  (PEP 639) and dropped the redundant classifier.
- **Dependency bounds**: optional Flask/Werkzeug deps upper-pinned to `<4.0`.
- **Observability**: `get_setting()` logs host-lookup failures at debug level
  instead of silently swallowing them.

### Added
- `MANIFEST.in` to ensure `py.typed`, `LICENSE`, and `README.md` ship in sdists.
- `CHANGELOG.md`.
