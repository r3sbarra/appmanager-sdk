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
