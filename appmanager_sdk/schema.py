"""
AppManager Manifest Schema and Builder.

Provides type-safe dataclasses to declare sub-application manifests directly in Python,
with support for validation, JSON serialization/deserialization, and file generation.

A ``manifest.json`` is the contract between a sub-app and the AppManager host. It tells
AppManager how to mount the app (entry point), what settings to render in the admin UI,
which admin blueprints to expose, and which background tasks to schedule. This module
is the single source of truth for that contract.

Two serialization shapes are produced by :meth:`AppManifest.to_dict`:

* ``settings_schema`` — a list of full setting definitions (key, type, label, default,
  description, is_secret) used by the admin UI to render the settings form.
* ``settings`` — a compact ``{key: {type, default, description}}`` map used by the
  host to resolve configured values at runtime.

Both are emitted so consumers can pick whichever shape they need.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# The set of setting ``type`` values the AppManager admin UI knows how to render.
# ``float`` is accepted for backward compatibility even though it is not in the
# documented UI set.
VALID_SETTING_TYPES = {"string", "integer", "boolean", "color", "textarea", "json", "float"}

# Named frequencies accepted for scheduled tasks. Anything else must be a raw
# cron expression (see ``_looks_like_cron``).
VALID_FREQUENCIES = {"hourly", "daily", "weekly", "monthly"}


def _looks_like_cron(value: str) -> bool:
    """Heuristic: a cron expression has 5 whitespace-separated fields."""
    parts = value.split()
    return len(parts) == 5 and all(re.fullmatch(r"[\d*/,\-?LW#]+", p) for p in parts)


def _sanitize_slug(slug_text: str) -> str:
    """
    Normalize a display name into a URL-safe slug.

    Lowercases, replaces any non-alphanumeric/underscore character with ``-``,
    collapses runs of ``-``, and strips leading/trailing ``-``/``_``. Falls back
    to ``"sub-app"`` if nothing usable remains.
    """
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]", "-", slug_text.strip().lower())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-_")
    return cleaned or "sub-app"


@dataclass
class Setting:
    """
    Represents a configurable setting displayed in the AppManager Admin UI.

    A setting is a single form field the operator can configure for a sub-app.
    The ``default`` value is what the app receives when the operator has not
    overridden it. For ``is_secret=True`` settings the default is redacted on
    serialization (see :meth:`_serialized_default`) so real secrets never leak
    into ``manifest.json``.
    """

    key: str
    type: str = "string"  # one of VALID_SETTING_TYPES
    label: Optional[str] = None  # human-readable label; falls back to the key
    default: Any = None  # value used when the operator has not configured one
    description: Optional[str] = None  # help text shown in the admin UI
    is_secret: bool = False  # if True, the default is redacted on serialization

    # Field reference (type / usage):
    #   key         (str)  — unique config key; also the runtime lookup key.
    #   type        (str)  — one of VALID_SETTING_TYPES; drives the admin form widget.
    #   label       (str|None) — display label; defaults to title-cased key.
    #   default     (Any)  — value returned when the operator hasn't overridden it.
    #   description (str|None) — help text under the field in the admin UI.
    #   is_secret   (bool) — True redacts the default on serialization.

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to the ``settings_schema`` entry shape consumed by the admin UI.

        Returns:
            A dict with keys ``key``, ``type``, ``label``, ``default``,
            ``description``, ``is_secret``. ``default`` is always present (even
            when None) so consumers can distinguish "unset" from "missing";
            other None-valued metadata keys are dropped.
        """
        data = {
            "key": self.key,
            "type": self.type,
            "label": self.label or self.key.replace("_", " ").title(),
            "default": self._serialized_default(),
            "description": self.description or "",
            "is_secret": self.is_secret,
        }
        # Keep 'default' even when None (meaningful distinction); drop other None metadata.
        return {k: v for k, v in data.items() if v is not None or k == "default"}

    def _serialized_default(self) -> Any:
        """
        Redact secret defaults so real values never land in manifest.json.

        Returns:
            ``"***REDACTED***"`` when this is a secret setting with a non-None
            default; otherwise the raw ``default`` value unchanged.
        """
        if self.is_secret and self.default is not None:
            return "***REDACTED***"
        return self.default


@dataclass
class AdminSection:
    """
    Represents a custom admin panel or blueprint mounted under /admin/apps/<slug>/<id>.

    ``blueprint`` follows the same ``module:variable`` convention as
    :attr:`AppManifest.entry_point` — it names a Flask blueprint object to mount
    into the AppManager admin area.
    """

    id: str
    label: str
    blueprint: str  # e.g. "admin_module:bp_var"
    icon: Optional[str] = "grid"  # icon name rendered next to the section label
    order: int = 10  # sort position within the admin sidebar

    # Field reference (type / usage):
    #   id        (str)  — unique section id; appears in the admin URL path.
    #   label     (str)  — display label in the admin sidebar.
    #   blueprint (str)  — "module:variable" Flask blueprint reference to mount.
    #   icon      (str|None) — icon name; default "grid".
    #   order     (int)  — sidebar sort position; lower sorts first.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "blueprint": self.blueprint,
            "icon": self.icon,
            "order": self.order,
        }


@dataclass
class ScheduledTask:
    """
    Represents a periodic background cron routine executed by the AppManager runner.

    ``frequency`` is either one of :data:`VALID_FREQUENCIES` or a raw 5-field cron
    expression (e.g. ``"0 3 * * *"``).
    """

    name: str
    entry_point: str  # e.g. "tasks:warm_cache"
    frequency: str = "hourly"  # "hourly", "daily", or cron expression

    # Field reference (type / usage):
    #   name        (str)  — unique task name.
    #   entry_point (str)  — "module:function" reference to the task callable.
    #   frequency   (str)  — one of VALID_FREQUENCIES or a 5-field cron expression.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "entry_point": self.entry_point,
            "frequency": self.frequency,
        }


# Allowed values for the ``robots`` SEO field. Anything else is rejected by
# :meth:`AppManifest.validate`.
VALID_ROBOTS_VALUES = {
    "index,follow",
    "index,nofollow",
    "noindex,follow",
    "noindex,nofollow",
    "index",
    "noindex",
    "follow",
    "nofollow",
    "none",
}


@dataclass
class SeoInfo:
    """
    Declarative SEO metadata for an AppManager sub-application.

    This is the contract between a sub-app and the AppManager host for search
    engine optimization. The app declares its SEO intent here; the host is
    responsible for rendering it into the served HTML ``<head>`` (and for
    emitting ``robots.txt`` / ``sitemap.xml``). All fields are optional — the
    host falls back to sensible defaults (e.g. ``name`` for the title).

    ``json_ld`` is a free-form dict serialized as-is into a ``<script
    type="application/ld+json">`` block (e.g. ``{"@type": "SoftwareApplication",
    ...}``).
    """

    title: Optional[str] = None  # overrides <title>; falls back to manifest name
    description: Optional[str] = None  # meta description
    keywords: Optional[List[str]] = None  # meta keywords
    canonical_url: Optional[str] = None  # canonical link href
    og_title: Optional[str] = None  # Open Graph title
    og_description: Optional[str] = None  # Open Graph description
    og_image: Optional[str] = None  # Open Graph image URL
    og_type: Optional[str] = None  # Open Graph type (e.g. "website")
    twitter_card: Optional[str] = None  # Twitter card type (e.g. "summary_large_image")
    twitter_image: Optional[str] = None  # Twitter image URL
    robots: Optional[str] = None  # one of VALID_ROBOTS_VALUES
    json_ld: Optional[Dict[str, Any]] = None  # raw JSON-LD structured data

    # Field reference (type / usage):
    #   title          (str|None) — <title>; falls back to manifest name.
    #   description    (str|None) — meta description.
    #   keywords       (list[str]|None) — meta keywords.
    #   canonical_url  (str|None) — canonical link href.
    #   og_title       (str|None) — Open Graph title.
    #   og_description (str|None) — Open Graph description.
    #   og_image       (str|None) — Open Graph image URL.
    #   og_type        (str|None) — Open Graph type.
    #   twitter_card   (str|None) — Twitter card type.
    #   twitter_image  (str|None) — Twitter image URL.
    #   robots         (str|None) — one of VALID_ROBOTS_VALUES.
    #   json_ld        (dict|None) — raw JSON-LD structured data.

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize to the ``seo`` block shape consumed by the host.

        Returns:
            A dict with only the non-None fields set, so optional SEO metadata
            is omitted from ``manifest.json`` when unset.
        """
        data: Dict[str, Any] = {
            "title": self.title,
            "description": self.description,
            "keywords": self.keywords,
            "canonical_url": self.canonical_url,
            "og_title": self.og_title,
            "og_description": self.og_description,
            "og_image": self.og_image,
            "og_type": self.og_type,
            "twitter_card": self.twitter_card,
            "twitter_image": self.twitter_image,
            "robots": self.robots,
            "json_ld": self.json_ld,
        }
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["SeoInfo"]:
        """
        Construct a SeoInfo from a dict, or return None if ``data`` is falsy.

        Unknown keys are ignored (forward-compatible). ``keywords`` is coerced
        to a list if given as a comma-separated string.

        Args:
            data: A dict, typically the ``seo`` block of a manifest.

        Returns:
            A :class:`SeoInfo` instance, or None if ``data`` is empty/None.
        """
        if not data:
            return None
        keywords = data.get("keywords")
        if isinstance(keywords, str):
            keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        return cls(
            title=data.get("title"),
            description=data.get("description"),
            keywords=keywords,
            canonical_url=data.get("canonical_url"),
            og_title=data.get("og_title"),
            og_description=data.get("og_description"),
            og_image=data.get("og_image"),
            og_type=data.get("og_type"),
            twitter_card=data.get("twitter_card"),
            twitter_image=data.get("twitter_image"),
            robots=data.get("robots"),
            json_ld=data.get("json_ld"),
        )


@dataclass
class AppManifest:
    """
    Full declarative specification of an AppManager sub-application or extension.

    This is the root object developers build to describe their app. It can be
    constructed directly, via the fluent ``add_*`` builder methods, or parsed
    back from an existing ``manifest.json`` with :meth:`from_dict`.

    ``app_type`` is either ``"standalone"`` (a full sub-app) or ``"extension"``
    (a feature bolted onto another app, which then requires ``target_app``).
    """

    name: str
    slug: Optional[str] = None  # URL-safe id; auto-derived from name if omitted
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    entry_point: str = "app:app"  # "module:variable" naming the WSGI app object
    health_check_path: str = "/health"
    app_type: str = "standalone"  # "standalone" or "extension"
    target_app: Optional[str] = None  # required when app_type == "extension"
    has_web_ui: bool = True
    requires_auth: bool = True
    # Database access request (approved/denied by admin at install time).
    requests_database: bool = False
    database_access_level: str = "scoped"  # "scoped" (default) | "full"
    database_description: str = ""  # human-readable justification shown to admin
    # Read-only auth access request (login state / display name / role only).
    requests_auth_readonly: bool = False
    settings: List[Setting] = field(default_factory=list)
    admin_sections: List[AdminSection] = field(default_factory=list)
    ui_slots: List[str] = field(default_factory=list)
    scheduled_tasks: List[ScheduledTask] = field(default_factory=list)
    seo: Optional[SeoInfo] = None  # declarative SEO metadata (see SeoInfo)

    def __post_init__(self) -> None:
        """
        Normalize the manifest after construction.

        Ensures the slug is always URL-safe and coerces any ``dict`` entries in
        the collection fields into their typed dataclass counterparts, so the
        rest of the code can assume concrete types.
        """
        if not self.slug:
            self.slug = _sanitize_slug(self.name)
        else:
            self.slug = _sanitize_slug(self.slug)

        # Normalize settings: accept either Setting objects or raw dicts.
        norm_settings: List[Setting] = []
        for s in self.settings:
            if isinstance(s, Setting):
                norm_settings.append(s)
            elif isinstance(s, dict):
                norm_settings.append(Setting(**s))
        self.settings = norm_settings

        # Normalize admin sections: accept either AdminSection objects or raw dicts.
        norm_sections: List[AdminSection] = []
        for a in self.admin_sections:
            if isinstance(a, AdminSection):
                norm_sections.append(a)
            elif isinstance(a, dict):
                norm_sections.append(AdminSection(**a))
        self.admin_sections = norm_sections

        # Normalize scheduled tasks: accept either ScheduledTask objects or raw dicts.
        norm_tasks: List[ScheduledTask] = []
        for t in self.scheduled_tasks:
            if isinstance(t, ScheduledTask):
                norm_tasks.append(t)
            elif isinstance(t, dict):
                norm_tasks.append(ScheduledTask(**t))
        self.scheduled_tasks = norm_tasks

        # Normalize SEO: accept either a SeoInfo object or a raw dict.
        if isinstance(self.seo, dict):
            self.seo = SeoInfo.from_dict(self.seo)
        elif self.seo is not None and not isinstance(self.seo, SeoInfo):
            self.seo = None

    def add_setting(
        self,
        key: str,
        type: str = "string",
        label: Optional[str] = None,
        default: Any = None,
        description: Optional[str] = None,
        is_secret: bool = False,
    ) -> "AppManifest":
        """
        Fluent builder: append a setting and return self for chaining.

        Args:
            key: Unique setting identifier (used as the config key at runtime).
            type: One of :data:`VALID_SETTING_TYPES` (e.g. ``"string"``, ``"integer"``).
            label: Human-readable label; defaults to the key with underscores
                replaced by spaces and title-cased.
            default: Value used when the operator has not configured one.
            description: Help text shown in the admin UI.
            is_secret: If True, the default is redacted on serialization.

        Returns:
            ``self`` so calls can be chained (e.g. ``m.add_setting(...).add_ui_slot(...)``).
        """
        self.settings.append(
            Setting(
                key=key,
                type=type,
                label=label,
                default=default,
                description=description,
                is_secret=is_secret,
            )
        )
        return self

    def add_admin_section(
        self, id: str, label: str, blueprint: str, icon: Optional[str] = "grid", order: int = 10
    ) -> "AppManifest":
        """
        Fluent builder: append an admin section and return self for chaining.

        Args:
            id: Unique section id (used in the admin URL path).
            label: Display label shown in the admin sidebar.
            blueprint: ``module:variable`` reference to a Flask blueprint to mount.
            icon: Icon name rendered next to the label (default ``"grid"``).
            order: Sort position within the admin sidebar (lower sorts first).

        Returns:
            ``self`` for chaining.
        """
        self.admin_sections.append(
            AdminSection(id=id, label=label, blueprint=blueprint, icon=icon, order=order)
        )
        return self

    def add_scheduled_task(
        self, name: str, entry_point: str, frequency: str = "hourly"
    ) -> "AppManifest":
        """
        Fluent builder: append a scheduled task and return self for chaining.

        Args:
            name: Unique task name.
            entry_point: ``module:function`` reference to the task callable.
            frequency: One of :data:`VALID_FREQUENCIES` or a 5-field cron expression.

        Returns:
            ``self`` for chaining.
        """
        self.scheduled_tasks.append(
            ScheduledTask(name=name, entry_point=entry_point, frequency=frequency)
        )
        return self

    def add_ui_slot(self, slot_name: str) -> "AppManifest":
        """
        Fluent builder: register a UI slot (deduplicated) and return self for chaining.

        Args:
            slot_name: Name of the UI slot this app renders into (e.g.
                ``"dashboard_widget"``). Duplicates are ignored.

        Returns:
            ``self`` for chaining.
        """
        if slot_name not in self.ui_slots:
            self.ui_slots.append(slot_name)
        return self

    def with_seo(self, **kwargs: Any) -> "AppManifest":
        """
        Fluent builder: set the app's SEO metadata and return self for chaining.

        Accepts any :class:`SeoInfo` field as a keyword argument (e.g.
        ``title``, ``description``, ``keywords``, ``canonical_url``,
        ``og_image``, ``robots``, ``json_ld``). Passing a ``SeoInfo`` instance
        as ``seo=...`` also works. Calling again merges/overwrites the previous
        SEO block.

        Returns:
            ``self`` for chaining.
        """
        if "seo" in kwargs and isinstance(kwargs["seo"], SeoInfo):
            self.seo = kwargs["seo"]
            return self
        current = self.seo.to_dict() if self.seo else {}
        current.update({k: v for k, v in kwargs.items() if v is not None})
        self.seo = SeoInfo.from_dict(current)
        return self

    def validate(self) -> List[str]:
        """
        Validates manifest fields against AppManager specification.

        Checks structural fields (name, slug, app_type, entry_point) plus the
        nested collections: setting types and duplicate keys, admin blueprint
        format, and scheduled-task frequency.

        Returns:
            A list of human-readable error strings; an empty list means the
            manifest is valid. Callers should treat any non-empty result as
            "do not deploy this manifest".
        """
        errors = []
        if not self.name or not self.name.strip():
            errors.append("Manifest 'name' is required.")
        if not self.slug or not self.slug.strip():
            errors.append("Manifest 'slug' is required.")
        if self.app_type not in ("standalone", "extension"):
            errors.append(
                f"Invalid app_type '{self.app_type}'. Must be 'standalone' or 'extension'."
            )
        if self.app_type == "extension" and not self.target_app:
            errors.append("Extension app_type requires 'target_app'.")
        if ":" not in self.entry_point:
            errors.append(f"entry_point '{self.entry_point}' must follow 'module:variable' format.")

        # Database access request validation.
        if self.requests_database and self.database_access_level not in ("scoped", "full"):
            errors.append(
                f"database_access_level '{self.database_access_level}' must be 'scoped' or 'full'."
            )

        # Setting validation: reject unknown types and duplicate keys.
        seen_keys = set()
        for s in self.settings:
            if s.type not in VALID_SETTING_TYPES:
                errors.append(
                    f"Setting '{s.key}' has invalid type '{s.type}'. "
                    f"Allowed: {', '.join(sorted(VALID_SETTING_TYPES))}"
                )
            if s.key in seen_keys:
                errors.append(f"Duplicate setting key '{s.key}'.")
            seen_keys.add(s.key)

        # AdminSection blueprint format: must be "module:variable".
        for a in self.admin_sections:
            if ":" not in a.blueprint:
                errors.append(
                    f"AdminSection '{a.id}' blueprint '{a.blueprint}' must follow 'module:variable' format."
                )

        # ScheduledTask frequency: named value or a valid cron expression.
        for t in self.scheduled_tasks:
            if t.frequency not in VALID_FREQUENCIES and not _looks_like_cron(t.frequency):
                errors.append(
                    f"ScheduledTask '{t.name}' frequency '{t.frequency}' must be one of "
                    f"{', '.join(sorted(VALID_FREQUENCIES))} or a cron expression."
                )

        # SEO validation: robots must be a known value; json_ld must be a dict.
        if self.seo is not None:
            if self.seo.robots and self.seo.robots not in VALID_ROBOTS_VALUES:
                errors.append(
                    f"SEO 'robots' value '{self.seo.robots}' is invalid. "
                    f"Allowed: {', '.join(sorted(VALID_ROBOTS_VALUES))}"
                )
            if self.seo.json_ld is not None and not isinstance(self.seo.json_ld, dict):
                errors.append("SEO 'json_ld' must be a JSON object (dict).")

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """
        Converts the manifest into a dictionary matching AppManager's manifest.json contract.

        Emits both the ``settings_schema`` (full definitions for the admin UI) and
        the compact ``settings`` map (for runtime resolution). Secret defaults are
        redacted in both shapes.

        Returns:
            A dict suitable for ``json.dumps``. Optional fields whose value is
            None are omitted. The two settings shapes are:

            - ``settings_schema``: list of full setting dicts (from
              :meth:`Setting.to_dict`).
            - ``settings``: compact ``{key: {type, default, description}}`` map.
        """
        settings_dict: Dict[str, Any] = {}
        settings_schema_list: List[Dict[str, Any]] = []

        for s in self.settings:
            s_obj = s if isinstance(s, Setting) else Setting(**s)
            s_dict = s_obj.to_dict()
            settings_schema_list.append(s_dict)
            # Compact runtime shape: type + redacted default + description.
            settings_dict[s_obj.key] = {
                "type": s_obj.type,
                "default": s_obj._serialized_default(),
                "description": s_obj.description or s_obj.label or "",
            }

        admin_sections_list = [
            (a.to_dict() if isinstance(a, AdminSection) else a) for a in self.admin_sections
        ]
        scheduled_tasks_list = [
            (t.to_dict() if isinstance(t, ScheduledTask) else t) for t in self.scheduled_tasks
        ]

        result: Dict[str, Any] = {
            "name": self.name,
            "slug": self.slug,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "entry_point": self.entry_point,
            "health_check_path": self.health_check_path,
            "app_type": self.app_type,
            "target_app": self.target_app,
            "has_web_ui": self.has_web_ui,
            "requires_auth": self.requires_auth,
            "requests_database": self.requests_database,
            "database_access_level": self.database_access_level,
            "database_description": self.database_description,
            "requests_auth_readonly": self.requests_auth_readonly,
            "settings": settings_dict,
            "settings_schema": settings_schema_list,
            "admin_sections": admin_sections_list,
            "ui_slots": self.ui_slots,
            "scheduled_tasks": scheduled_tasks_list,
            "seo": self.seo.to_dict() if self.seo else None,
        }

        # Filter out None values so optional fields are omitted from the JSON.
        return {k: v for k, v in result.items() if v is not None}

    def to_json(self, indent: int = 2) -> str:
        """
        Serialize the manifest to a pretty-printed JSON string.

        Args:
            indent: Number of spaces per indentation level in the output.

        Returns:
            The manifest as a JSON string (via :meth:`to_dict`).
        """
        return json.dumps(self.to_dict(), indent=indent)

    def save_manifest(self, path: str = "manifest.json") -> str:
        """
        Writes manifest.json to the specified file path.

        Args:
            path: Destination file path (relative or absolute). Parent
                directories are created as needed.

        Returns:
            The absolute path of the written file.
        """
        abs_path = os.path.abspath(path)
        os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(self.to_json(indent=2) + "\n")
        return abs_path

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppManifest":
        """
        Constructs an AppManifest instance from a dictionary.

        Accepts either the ``settings_schema`` list form or the compact ``settings``
        dict form. Unknown keys are ignored (forward-compatible with newer manifest
        versions), and nested entries are extracted field-by-field rather than
        passed as ``**kwargs`` so extra keys never crash deserialization.

        Args:
            data: A manifest dict, typically parsed from ``manifest.json``.
                Recognized keys: ``name``, ``slug``, ``version``, ``description``,
                ``author``, ``entry_point``, ``health_check_path``, ``app_type``,
                ``target_app``, ``has_web_ui`` (or legacy ``has_ui``),
                ``requires_auth``, ``settings``/``settings_schema``,
                ``admin_sections``, ``ui_slots``, ``scheduled_tasks``.

        Returns:
            A new :class:`AppManifest` instance.
        """
        settings_raw = data.get("settings_schema") or data.get("settings") or []
        settings_list: List[Setting] = []

        if isinstance(settings_raw, list):
            # settings_schema form: a list of full setting definitions.
            for item in settings_raw:
                if isinstance(item, dict):
                    settings_list.append(
                        Setting(
                            key=item.get("key", ""),
                            type=item.get("type", "string"),
                            label=item.get("label"),
                            default=item.get("default"),
                            description=item.get("description"),
                            is_secret=item.get("is_secret", False),
                        )
                    )
        elif isinstance(settings_raw, dict):
            # settings form: a compact {key: {...}} map. Preserve is_secret/label.
            for key, val in settings_raw.items():
                if isinstance(val, dict):
                    settings_list.append(
                        Setting(
                            key=key,
                            type=val.get("type", "string"),
                            label=val.get("label"),
                            default=val.get("default"),
                            description=val.get("description"),
                            is_secret=val.get("is_secret", False),
                        )
                    )
                else:
                    # Bare value shorthand: {key: default}.
                    settings_list.append(Setting(key=key, default=val))

        # Extract admin sections field-by-field (ignore unknown keys).
        admin_sections_raw = data.get("admin_sections") or []
        sections_list = [
            AdminSection(
                id=a.get("id", ""),
                label=a.get("label", ""),
                blueprint=a.get("blueprint", ""),
                icon=a.get("icon", "grid"),
                order=a.get("order", 10),
            )
            if isinstance(a, dict)
            else a
            for a in admin_sections_raw
        ]

        # Extract scheduled tasks field-by-field (ignore unknown keys).
        scheduled_tasks_raw = data.get("scheduled_tasks") or []
        tasks_list = [
            ScheduledTask(
                name=t.get("name", ""),
                entry_point=t.get("entry_point", ""),
                frequency=t.get("frequency", "hourly"),
            )
            if isinstance(t, dict)
            else t
            for t in scheduled_tasks_raw
        ]

        return cls(
            name=data.get("name", "Untitled Sub-App"),
            slug=data.get("slug"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", ""),
            entry_point=data.get("entry_point", "app:app"),
            health_check_path=data.get("health_check_path", "/health"),
            app_type=data.get("app_type", "standalone"),
            target_app=data.get("target_app"),
            has_web_ui=data.get("has_web_ui", data.get("has_ui", True)),
            requires_auth=data.get("requires_auth", True),
            requests_database=data.get("requests_database", False),
            database_access_level=data.get("database_access_level", "scoped"),
            database_description=data.get("database_description", ""),
            requests_auth_readonly=data.get("requests_auth_readonly", False),
            settings=settings_list,
            admin_sections=sections_list,
            ui_slots=data.get("ui_slots", []),
            scheduled_tasks=tasks_list,
            seo=SeoInfo.from_dict(data.get("seo")),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AppManifest":
        """
        Construct an AppManifest from a JSON string.

        Args:
            json_str: A JSON-encoded manifest string.

        Returns:
            A new :class:`AppManifest` instance.
        """
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def from_file(cls, path: str = "manifest.json") -> "AppManifest":
        """
        Construct an AppManifest by reading and parsing a manifest.json file.

        Args:
            path: Path to a ``manifest.json`` file.

        Returns:
            A new :class:`AppManifest` instance.
        """
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def cli(self) -> None:
        """
        CLI hook that can be called from `if __name__ == '__main__': manifest.cli()`.
        Generates manifest.json if `--generate-manifest` is present in sys.argv.

        Usage:
            In your app entrypoint:
                if __name__ == "__main__":
                    manifest.cli()
            Then run:  python app.py --generate-manifest [--out path.json]

        Args:
            (none) — reads ``sys.argv`` directly for ``--generate-manifest`` and
            ``--out``/``-o``.

        Returns:
            None. Exits the process (``sys.exit(0)``) after writing the file, so
            it can be used as a standalone entrypoint.
        """
        if "--generate-manifest" in sys.argv or "generate-manifest" in sys.argv:
            out_file = "manifest.json"
            for i, arg in enumerate(sys.argv):
                if arg in ("--out", "-o") and i + 1 < len(sys.argv):
                    out_file = sys.argv[i + 1]
            saved = self.save_manifest(out_file)
            print(f"✓ Successfully generated manifest: {saved}")
            sys.exit(0)
