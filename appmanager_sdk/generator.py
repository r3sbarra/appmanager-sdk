"""
AppManager Manifest Generator.

Utilities to discover, inspect, and export AppManifest instances from Python modules and files.

DISCOVERY MODEL: a manifest can live in several places — as a module-level variable
(``manifest``, ``app_manifest``, ``__appmanager_manifest__``), attached to a Flask app
object, or as a raw dict. This module searches those candidates in a defined order.

SECURITY: loading a manifest from a Python module **executes that module**. Only run
this on code you trust; never on untrusted input (e.g. unvetted PRs in CI).
"""

import contextlib
import importlib.util
import os
import sys
from typing import Any, Iterator, Optional, Tuple

from appmanager_sdk.schema import AppManifest


@contextlib.contextmanager
def _temporary_sys_path(paths) -> Iterator[None]:
    """
    Temporarily prepend paths to sys.path, restoring the original on exit.

    Loading a target module may need its directory on ``sys.path`` to resolve
    relative imports. We add them only for the duration of the load and restore
    the original list afterward, so repeated calls never pollute ``sys.path``
    (which could shadow stdlib modules or leak stale temp dirs).
    """
    original = sys.path[:]
    for p in paths:
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        yield
    finally:
        sys.path[:] = original


def load_manifest_from_module(
    target_ref: str, base_dir: Optional[str] = None
) -> Tuple[Optional[AppManifest], Optional[str]]:
    """
    Loads an AppManifest from a Python target reference.
    target_ref can be:
      - 'module:manifest_var' (e.g. 'app:manifest')
      - 'module:app_var' (e.g. 'app:app', if app.manifest exists)
      - 'module' (e.g. 'app', searches for 'manifest' or 'app.manifest')
      - 'path/to/app.py' or 'path/to/app.py:manifest'

    Returns ``(manifest, None)`` on success or ``(None, error_message)`` on failure.

    SECURITY: this executes the target module to discover the manifest. Only
    run it on code you trust; never on untrusted input.
    """
    if base_dir:
        abs_base = os.path.abspath(base_dir)
    else:
        abs_base = os.path.abspath(os.getcwd())

    target_var = None
    file_or_module = target_ref

    # Split "module:variable" into its two parts, if present.
    if ":" in target_ref:
        file_or_module, target_var = target_ref.split(":", 1)

    # Decide whether the target is a file path or an importable module name.
    # A bare name like "app" is treated as a file if "app.py" exists locally.
    mod = None
    cand_file = (
        file_or_module
        if (file_or_module.endswith(".py") or os.path.exists(file_or_module))
        else f"{file_or_module}.py"
    )
    if os.path.exists(cand_file):
        # Load from a concrete file path via importlib.
        file_path = os.path.abspath(cand_file)
        file_dir = os.path.dirname(file_path)
        module_name = os.path.splitext(os.path.basename(file_path))[0]

        spec = importlib.util.spec_from_file_location(f"appmanager_gen_{module_name}", file_path)
        if spec is None or spec.loader is None:
            return None, f"Could not create module spec from '{file_path}'"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        try:
            # Execute the module with its dir + base_dir on sys.path (restored after).
            with _temporary_sys_path([abs_base, file_dir]):
                spec.loader.exec_module(mod)
        except Exception as e:
            return None, f"Failed executing module '{file_path}': {e}"
        finally:
            # Remove the temp module from sys.modules so it doesn't linger.
            sys.modules.pop(spec.name, None)
    else:
        # Standard import by module name.
        try:
            with _temporary_sys_path([abs_base]):
                mod = importlib.import_module(file_or_module)
        except Exception as e:
            return None, f"Failed importing module '{file_or_module}': {e}"

    # 1. If an explicit variable was requested, use exactly that.
    if target_var:
        if not hasattr(mod, target_var):
            return None, f"Module '{file_or_module}' has no attribute '{target_var}'"
        obj = getattr(mod, target_var)
        manifest = _extract_manifest_from_object(obj)
        if manifest:
            return manifest, None
        return (
            None,
            f"Object '{target_var}' in '{file_or_module}' is not an AppManifest instance or provider.",
        )

    # 2. Search common candidate attributes in module, in priority order.
    candidates = [
        "manifest",
        "app_manifest",
        "__appmanager_manifest__",
        "app",
        "application",
        "extension",
    ]
    for attr in candidates:
        if hasattr(mod, attr):
            obj = getattr(mod, attr)
            manifest = _extract_manifest_from_object(obj)
            if manifest:
                return manifest, None

    return (
        None,
        f"Could not find an AppManifest in '{target_ref}'. Tried attributes: {', '.join(candidates)}",
    )


def _extract_manifest_from_object(obj: Any) -> Optional[AppManifest]:
    """
    Extracts or builds an AppManifest from an object.
    Supports:
      - AppManifest instance
      - Flask app with .manifest or .__appmanager_manifest__ or .extensions['appmanager_manifest']
      - Dict matching manifest schema

    Returns None if the object does not yield a manifest.
    """
    if isinstance(obj, AppManifest):
        return obj

    # Flask apps often expose the manifest as a plain attribute.
    if hasattr(obj, "manifest"):
        manifest_attr = getattr(obj, "manifest")
        if isinstance(manifest_attr, AppManifest):
            return manifest_attr

    # The SDK's own marker attribute (set by AppManager.init_app).
    if hasattr(obj, "__appmanager_manifest__"):
        m = getattr(obj, "__appmanager_manifest__")
        if isinstance(m, AppManifest):
            return m
        if isinstance(m, dict):
            return AppManifest.from_dict(m)

    # Flask extension registry (set by AppManager.init_app).
    if hasattr(obj, "extensions") and isinstance(obj.extensions, dict):
        if "appmanager_manifest" in obj.extensions:
            m = obj.extensions["appmanager_manifest"]
            if isinstance(m, AppManifest):
                return m

    # A raw dict that looks like a manifest.
    if isinstance(obj, dict) and "name" in obj and ("slug" in obj or "entry_point" in obj):
        try:
            return AppManifest.from_dict(obj)
        except Exception:
            return None

    return None


def generate_manifest_file(
    target_ref: str, output_path: str = "manifest.json", base_dir: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Generates manifest.json from a Python reference.
    Returns (success, message_or_path).

    Loads the manifest, validates it, and writes it to ``output_path``.
    """
    manifest, err = load_manifest_from_module(target_ref, base_dir=base_dir)
    if not manifest:
        return False, err or "Unknown manifest discovery error."

    errors = manifest.validate()
    if errors:
        return False, f"Manifest validation failed: {'; '.join(errors)}"

    saved_path = manifest.save_manifest(output_path)
    return True, saved_path
