"""
AppManager SDK
Lightweight developer SDK and manifest generator for AppManager sub-applications and extensions.
"""

from appmanager_sdk.client import (
    AppManagerClient,
    client,
    get_current_user,
    require_auth,
)
from appmanager_sdk.schema import (
    AdminSection,
    AppManifest,
    ScheduledTask,
    SeoInfo,
    Setting,
)

try:
    from appmanager_sdk.flask import AppManager
except ImportError:
    AppManager = None  # type: ignore

__version__ = "0.1.0"

__all__ = [
    "AppManifest",
    "Setting",
    "AdminSection",
    "ScheduledTask",
    "SeoInfo",
    "AppManagerClient",
    "client",
    "get_current_user",
    "require_auth",
    "AppManager",
    "__version__",
]
