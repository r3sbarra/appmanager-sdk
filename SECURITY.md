# Security Policy

## Supported Versions

We provide security updates for the following versions of `appmanager-sdk`:

| Version | Supported          | Python Versions       |
|---------|--------------------|-----------------------|
| 0.1.x   | :white_check_mark: | >= 3.10, <= 3.13      |
| < 0.1.0 | :x:                | N/A                   |

---

## Reporting a Vulnerability

Please submit an issue directly to our [GitHub Issues Tracker](https://github.com/r3sbarra/appmanager-sdk/issues) with the following details:

- **Summary**: A clear and concise description of the issue or unexpected behavior.
- **Reproduction**: Minimal steps to reproduce or proof-of-concept (PoC) code.
- **Environment**: Affected SDK version, Python version, and operating system.
- **Impact & Mitigation**: Potential impact and any proposed fixes or mitigations.

---

## Security Architecture & Threat Model

Developers integrating `appmanager-sdk` into their sub-applications and extensions should be aware of the following security considerations:

### 1. Header-Based Identity Forwarding

`AppManagerClient` extracts authenticated user identity from incoming request headers (`X-AppManager-User-Id`, `X-AppManager-User-Email`, `X-AppManager-User-Role`).

- **Gateway Requirement**: Endpoints guarded by `@require_auth` or consuming `get_current_user()` **must only be deployed behind a trusted AppManager gateway or reverse proxy**.
- **Header Stripping**: The upstream gateway MUST strip all incoming untrusted `X-AppManager-*` headers from external clients before forwarding requests to the sub-app.
- **HMAC Header Signing**: When deploying in multi-tenant or distributed environments, configure `APPMANAGER_HEADER_SECRET` (or pass `header_secret` to `AppManagerClient`). The gateway signs the identity payload (`User-Id|User-Email|User-Role`) using HMAC-SHA256 in `X-AppManager-Signature`. Requests with missing or mismatched signatures are automatically rejected using constant-time digest comparison (`hmac.compare_digest`).

### 2. Setting Secrets Redaction

When defining application settings via `Setting(..., is_secret=True)` or `manifest.add_setting(..., is_secret=True)`:
- Secret defaults are automatically redacted (`"***"`) during `to_dict()` and `to_json()` manifest serialization to prevent accidental leakage into version control or manifest distribution channels.
- Runtime secret resolution should occur via environment variables (`APPMANAGER_CONFIG_<KEY>`) or host secret storage.

### 3. Dynamic Manifest Inspection

The CLI command `appmanager-sdk generate <target>` loads and executes the specified Python module or file to inspect the manifest:
- **Caution**: Only run `appmanager-sdk generate` on trusted source code. Executing generator commands against untrusted code can lead to arbitrary code execution.
