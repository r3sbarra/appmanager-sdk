from flask import Flask

from appmanager_sdk import AppManager, AppManifest


def test_flask_extension_init():
    app = Flask("test_ext_app")
    manifest = AppManifest(
        name="Flask Ext App", slug="flask-ext-app", version="1.0.0", health_check_path="/healthz"
    )

    mgr = AppManager(app, manifest=manifest)
    assert app.manifest == manifest
    assert app.extensions["appmanager"] == mgr

    with app.test_client() as client:
        res = client.get("/healthz")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "healthy"
        assert data["app_slug"] == "flask-ext-app"


def test_flask_extension_kwargs_and_dict(tmp_path):
    # Test kwargs initialization
    app1 = Flask("app1")
    mgr1 = AppManager(app1, name="Kwargs App", version="2.0.0")
    mgr1.add_setting("api_key", type="string", is_secret=True)
    assert app1.manifest.slug == "kwargs-app"
    assert any(s.key == "api_key" for s in app1.manifest.settings)

    # Test dict initialization
    app2 = Flask("app2")
    mgr2 = AppManager()
    mgr2.init_app(app2, manifest={"name": "Dict App", "version": "1.2.0"})
    assert app2.manifest.slug == "dict-app"

    # Test CLI runner for manifest generate
    runner = app1.test_cli_runner()
    out_file = str(tmp_path / "manifest.json")
    result = runner.invoke(args=["manifest", "generate", "--out", out_file])
    assert result.exit_code == 0
    assert "Generated manifest" in result.output
