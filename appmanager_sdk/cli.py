"""
AppManager SDK Command Line Interface.

Provides developer tools for sub-app developers to generate, inspect, and validate manifests.

Commands:
  generate  — export manifest.json from a Python module/file (executes the target).
  validate  — check a manifest.json or Python module against the spec.
  init      — scaffold a minimal Python entrypoint using AppManifest.
"""

import argparse
import os
import re
import sys

from appmanager_sdk import __version__
from appmanager_sdk.generator import generate_manifest_file, load_manifest_from_module
from appmanager_sdk.schema import AppManifest


def main(argv=None) -> int:
    """Entrypoint for the ``appmanager-sdk`` console script. Returns a process exit code."""
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="appmanager-sdk",
        description="Lightweight SDK & Manifest Generator for AppManager Sub-Apps and Extensions.",
    )
    parser.add_argument("--version", "-v", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Command: generate
    gen_parser = subparsers.add_parser(
        "generate", help="Generate manifest.json from a Python file or module."
    )
    gen_parser.add_argument(
        "target",
        nargs="?",
        default="app:app",
        help="Target reference (e.g. 'app:manifest', 'app:app', 'app.py', 'main:manifest'). Default: 'app:app'",
    )
    gen_parser.add_argument(
        "--out",
        "-o",
        default="manifest.json",
        help="Output destination path. Default: 'manifest.json'",
    )

    # Command: validate
    val_parser = subparsers.add_parser(
        "validate", help="Validate a manifest.json file or Python module."
    )
    val_parser.add_argument(
        "target",
        nargs="?",
        default="manifest.json",
        help="Path to manifest.json or Python target (e.g. 'app:manifest'). Default: 'manifest.json'",
    )

    # Command: init
    init_parser = subparsers.add_parser(
        "init", help="Scaffold a minimal Python entrypoint using AppManifest."
    )
    init_parser.add_argument(
        "--name", "-n", default="My Sub-App", help="Display name of the sub-app."
    )
    init_parser.add_argument("--slug", "-s", default=None, help="Slug for the sub-app.")
    init_parser.add_argument(
        "--out", "-o", default="app.py", help="File to write scaffolded code to."
    )

    args = parser.parse_args(argv)

    if not args.command or args.command == "generate":
        target = getattr(args, "target", "app:app") or "app:app"
        out_path = getattr(args, "out", "manifest.json") or "manifest.json"

        # Convenience: if no explicit target and app.py is absent, look for a
        # common entrypoint file (main.py / wsgi.py / run.py) and use its app.
        if target == "app:app" and not os.path.exists("app.py"):
            for cand in ["main.py", "wsgi.py", "run.py"]:
                if os.path.exists(cand):
                    target = f"{cand[:-3]}:app"
                    break

        print(f"Generating manifest from '{target}' -> '{out_path}'...")
        print("⚠️  Executing target to extract manifest — only run on code you trust.")
        ok, msg = generate_manifest_file(target, output_path=out_path)
        if ok:
            print(f"✓ Successfully generated {msg}")
            return 0
        else:
            print(f"✗ Failed generating manifest: {msg}", file=sys.stderr)
            return 1

    elif args.command == "validate":
        target = args.target
        if os.path.isfile(target) and target.endswith(".json"):
            # Validate a static manifest.json (no code execution).
            try:
                manifest = AppManifest.from_file(target)
                errors = manifest.validate()
                if errors:
                    print(f"✗ Validation errors in '{target}':", file=sys.stderr)
                    for e in errors:
                        print(f"  - {e}", file=sys.stderr)
                    return 1
                print(f"✓ '{target}' is valid for sub-app '{manifest.name}' ({manifest.slug}).")
                return 0
            except Exception as e:
                print(f"✗ Failed to parse JSON manifest '{target}': {e}", file=sys.stderr)
                return 1
        else:
            # Validate a Python module (executes it to discover the manifest).
            mod_manifest, mod_err = load_manifest_from_module(target)
            if not mod_manifest:
                print(f"✗ Validation failed: {mod_err}", file=sys.stderr)
                return 1
            errors = mod_manifest.validate()
            if errors:
                print(f"✗ Validation errors in '{target}':", file=sys.stderr)
                for err_item in errors:
                    print(f"  - {err_item}", file=sys.stderr)
                return 1
            print(
                f"✓ Python manifest '{target}' is valid for sub-app '{mod_manifest.name}' ({mod_manifest.slug})."
            )
            return 0

    elif args.command == "init":
        name = args.name
        slug = args.slug or name.lower().replace(" ", "-")
        # Sanitize slug to URL-safe chars; escape name as a Python string literal
        # to prevent code injection via quotes/backslashes in the template.
        slug = re.sub(r"[^a-z0-9_\-]", "-", slug).strip("-") or "sub-app"
        name_lit = repr(name)
        slug_lit = repr(slug)
        # HTML-escape name for the generated page markup (XSS-safe).
        name_html = (
            name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )
        out_file = args.out

        # Refuse to overwrite an existing file.
        if os.path.exists(out_file):
            print(
                f"✗ Target file '{out_file}' already exists. Aborting to avoid overwrite.",
                file=sys.stderr,
            )
            return 1

        # Scaffold a minimal Flask entrypoint. The name/slug are injected as
        # escaped literals (name_lit/slug_lit) and HTML-escaped (name_html) so
        # user input can never break out of the template.
        template = f'''"""
{name} - AppManager Sub-Application
"""
from flask import Flask, jsonify, request
from appmanager_sdk import AppManifest, Setting, AppManagerClient

app = Flask(__name__)
client = AppManagerClient({slug_lit})

# Declarative AppManager Manifest
manifest = AppManifest(
    name={name_lit},
    slug={slug_lit},
    version="1.0.0",
    description="A modern sub-application built for AppManager.",
    entry_point="app:app",
    health_check_path="/health",
    has_web_ui=True,
    requires_auth=True,
    settings=[
        Setting(key="api_key", type="string", default="demo-key", description="API Key"),
        Setting(key="refresh_interval", type="integer", default=60, label="Refresh Rate (s)"),
    ],
    ui_slots=["dashboard_widget"],
)

@app.route("/")
@client.require_auth(role="user")
def index():
    user = client.get_current_user(request.headers)
    api_key = client.get_setting("api_key", default="demo-key")
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>{name_html}</title></head>
    <body style="font-family: sans-serif; background: #0f172a; color: white; padding: 2rem;">
      <h1>Hello, {{user['email'] if user else 'Guest'}}</h1>
      <p>Welcome to {name_html}!</p>
      <p>Configured API Key: <code>{{api_key}}</code></p>
    </body>
    </html>
    """

@app.route("/health")
def health():
    return jsonify({{"status": "healthy", "slug": "{slug}", "version": "1.0.0"}})

if __name__ == "__main__":
    import sys
    if "--generate-manifest" in sys.argv or "generate-manifest" in sys.argv:
        manifest.cli()
    else:
        app.run(port=5001, debug=True)
'''
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(template)
        print(f"✓ Initialized sub-app template at '{out_file}'")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
