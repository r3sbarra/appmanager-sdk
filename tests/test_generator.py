import os

from appmanager_sdk import AppManifest
from appmanager_sdk.generator import generate_manifest_file, load_manifest_from_module


def test_load_manifest_from_python_file(tmp_path):
    py_file = tmp_path / "sample_app.py"
    py_file.write_text("""
from appmanager_sdk import AppManifest, Setting

manifest = AppManifest(
    name="Sample Sub-App",
    slug="sample-sub-app",
    version="1.0.0",
    settings=[
        Setting(key="theme", default="dark")
    ]
)

def create_app():
    return None
""")

    manifest, err = load_manifest_from_module(str(py_file))
    assert err is None
    assert manifest is not None
    assert manifest.name == "Sample Sub-App"
    assert manifest.slug == "sample-sub-app"
    assert len(manifest.settings) == 1
    assert manifest.settings[0].key == "theme"


def test_generate_manifest_file_from_module(tmp_path):
    py_file = tmp_path / "custom_app.py"
    py_file.write_text("""
from appmanager_sdk import AppManifest

custom_manifest = AppManifest(
    name="Custom Pipeline",
    slug="custom-pipeline",
    entry_point="custom_app:server"
)
""")

    out_json = tmp_path / "output_manifest.json"
    ok, msg = generate_manifest_file(f"{py_file}:custom_manifest", output_path=str(out_json))
    assert ok is True
    assert os.path.exists(out_json)

    loaded = AppManifest.from_file(str(out_json))
    assert loaded.name == "Custom Pipeline"
    assert loaded.slug == "custom-pipeline"
    assert loaded.entry_point == "custom_app:server"
