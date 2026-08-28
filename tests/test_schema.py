import json

from appmanager_sdk import AdminSection, AppManifest, ScheduledTask, Setting


def test_manifest_creation_and_defaults():
    manifest = AppManifest(
        name="Test Analytics App",
        slug="test-analytics-app",
        version="1.2.0",
        description="Analytics test sub-app",
    )
    assert manifest.name == "Test Analytics App"
    assert manifest.slug == "test-analytics-app"
    assert manifest.entry_point == "app:app"
    assert manifest.health_check_path == "/health"
    assert manifest.has_web_ui is True
    assert manifest.requires_auth is True
    assert manifest.settings == []


def test_manifest_slug_auto_generation():
    manifest = AppManifest(name="My Super Cool Sub-App!")
    assert manifest.slug == "my-super-cool-sub-app"


def test_manifest_fluent_builder():
    manifest = (
        AppManifest(name="User Flairs", app_type="extension", target_app="appmanager")
        .add_setting("max_flairs", type="integer", default=3, label="Max Flairs")
        .add_setting("badge_color", type="color", default="#38bdf8", label="Badge Color")
        .add_admin_section(
            "presets", "Flair Presets", "flairs_admin:presets_bp", icon="tag", order=10
        )
        .add_ui_slot("user_badge")
        .add_scheduled_task("cleanup_flairs", "tasks:cleanup", frequency="daily")
    )

    data = manifest.to_dict()
    assert data["name"] == "User Flairs"
    assert data["app_type"] == "extension"
    assert data["target_app"] == "appmanager"
    assert len(data["settings_schema"]) == 2
    assert data["settings_schema"][0]["key"] == "max_flairs"
    assert data["settings_schema"][0]["type"] == "integer"
    assert data["settings"]["max_flairs"]["default"] == 3
    assert len(data["admin_sections"]) == 1
    assert data["admin_sections"][0]["blueprint"] == "flairs_admin:presets_bp"
    assert data["ui_slots"] == ["user_badge"]
    assert len(data["scheduled_tasks"]) == 1
    assert data["scheduled_tasks"][0]["frequency"] == "daily"


def test_manifest_serialization_and_deserialization(tmp_path):
    manifest = AppManifest(
        name="Commerce Store",
        slug="commerce-store",
        version="2.0.0",
        settings=[
            Setting(key="currency", default="USD", description="Store Currency"),
            Setting(key="tax_rate", type="float", default=0.08),
        ],
        admin_sections=[AdminSection(id="orders", label="Orders", blueprint="orders:bp")],
        ui_slots=["dashboard_widget"],
        scheduled_tasks=[
            ScheduledTask(name="sync_inventory", entry_point="tasks:sync", frequency="hourly")
        ],
    )

    json_str = manifest.to_json()
    parsed = json.loads(json_str)
    assert parsed["name"] == "Commerce Store"
    assert parsed["slug"] == "commerce-store"

    # Save to file
    out_file = tmp_path / "manifest.json"
    saved = manifest.save_manifest(str(out_file))
    assert str(out_file) == saved

    # Read back from file
    loaded = AppManifest.from_file(str(out_file))
    assert loaded.name == "Commerce Store"
    assert loaded.slug == "commerce-store"
    assert len(loaded.settings) == 2
    assert loaded.settings[0].key == "currency"
    assert loaded.settings[0].default == "USD"
    assert len(loaded.admin_sections) == 1
    assert loaded.admin_sections[0].id == "orders"
    assert loaded.ui_slots == ["dashboard_widget"]


def test_manifest_validation():
    valid_manifest = AppManifest(name="Valid App", entry_point="main:app")
    assert valid_manifest.validate() == []

    invalid_manifest = AppManifest(name="", entry_point="invalid_entrypoint")
    errors = invalid_manifest.validate()
    assert len(errors) >= 2
    assert any("name" in e.lower() for e in errors)
    assert any("entry_point" in e.lower() for e in errors)


def test_manifest_database_and_auth_fields():
    manifest = AppManifest(
        name="DB App",
        requests_database=True,
        database_access_level="scoped",
        database_description="Needs a table for user preferences",
        requests_auth_readonly=True,
    )
    data = manifest.to_dict()
    assert data["requests_database"] is True
    assert data["database_access_level"] == "scoped"
    assert data["database_description"] == "Needs a table for user preferences"
    assert data["requests_auth_readonly"] is True

    # Round-trip through JSON
    loaded = AppManifest.from_dict(json.loads(manifest.to_json()))
    assert loaded.requests_database is True
    assert loaded.database_access_level == "scoped"
    assert loaded.database_description == "Needs a table for user preferences"
    assert loaded.requests_auth_readonly is True

    # Defaults when not requested
    plain = AppManifest(name="Plain App")
    assert plain.requests_database is False
    assert plain.database_access_level == "scoped"
    assert plain.requests_auth_readonly is False


def test_manifest_database_access_level_validation():
    bad = AppManifest(name="Bad", requests_database=True, database_access_level="everything")
    errors = bad.validate()
    assert any("database_access_level" in e for e in errors)

    good = AppManifest(name="Good", requests_database=True, database_access_level="full")
    assert good.validate() == []


# ---------- SEO ----------


def test_manifest_seo_roundtrip():
    manifest = AppManifest(
        name="SEO App",
        seo={
            "title": "SEO App — Analytics",
            "description": "A sub-app with SEO metadata.",
            "keywords": ["analytics", "dashboard", "seo"],
            "canonical_url": "https://example.com/apps/seo-app/",
            "og_title": "SEO App",
            "og_image": "https://example.com/og.png",
            "og_type": "website",
            "twitter_card": "summary_large_image",
            "robots": "index,follow",
            "json_ld": {"@type": "SoftwareApplication", "name": "SEO App"},
        },
    )
    data = manifest.to_dict()
    assert data["seo"]["title"] == "SEO App — Analytics"
    assert data["seo"]["description"] == "A sub-app with SEO metadata."
    assert data["seo"]["keywords"] == ["analytics", "dashboard", "seo"]
    assert data["seo"]["canonical_url"] == "https://example.com/apps/seo-app/"
    assert data["seo"]["og_type"] == "website"
    assert data["seo"]["twitter_card"] == "summary_large_image"
    assert data["seo"]["robots"] == "index,follow"
    assert data["seo"]["json_ld"] == {"@type": "SoftwareApplication", "name": "SEO App"}

    # Round-trip through JSON
    loaded = AppManifest.from_dict(json.loads(manifest.to_json()))
    assert loaded.seo is not None
    assert loaded.seo.title == "SEO App — Analytics"
    assert loaded.seo.keywords == ["analytics", "dashboard", "seo"]
    assert loaded.seo.robots == "index,follow"
    assert loaded.seo.json_ld == {"@type": "SoftwareApplication", "name": "SEO App"}


def test_manifest_seo_fluent_builder():
    manifest = (
        AppManifest(name="Flair App")
        .with_seo(title="Flair App", description="User flairs", robots="noindex,nofollow")
        .with_seo(keywords=["flair", "badge"], og_image="https://example.com/flair.png")
    )
    assert manifest.seo is not None
    assert manifest.seo.title == "Flair App"
    assert manifest.seo.description == "User flairs"
    assert manifest.seo.robots == "noindex,nofollow"
    assert manifest.seo.keywords == ["flair", "badge"]
    assert manifest.seo.og_image == "https://example.com/flair.png"

    data = manifest.to_dict()
    assert data["seo"]["title"] == "Flair App"
    assert data["seo"]["keywords"] == ["flair", "badge"]


def test_manifest_seo_optional_and_backward_compat():
    # No SEO block -> omitted from dict, None on parse.
    plain = AppManifest(name="Plain")
    assert plain.seo is None
    assert "seo" not in plain.to_dict()
    loaded = AppManifest.from_dict(plain.to_dict())
    assert loaded.seo is None

    # Empty seo dict -> None.
    empty = AppManifest(name="Empty", seo={})
    assert empty.seo is None


def test_manifest_seo_validation():
    bad = AppManifest(name="Bad", seo={"robots": "banana"})
    errors = bad.validate()
    assert any("robots" in e for e in errors)

    bad_jsonld = AppManifest(name="BadJson", seo={"json_ld": "not-a-dict"})
    errors = bad_jsonld.validate()
    assert any("json_ld" in e for e in errors)

    good = AppManifest(name="Good", seo={"robots": "noindex,nofollow", "json_ld": {"@type": "WebSite"}})
    assert good.validate() == []


def test_manifest_seo_keywords_string_coercion():
    manifest = AppManifest(name="Coerce", seo={"keywords": "alpha, beta,gamma"})
    assert manifest.seo is not None
    assert manifest.seo.keywords == ["alpha", "beta", "gamma"]
