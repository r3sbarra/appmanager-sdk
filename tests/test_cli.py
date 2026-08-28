from appmanager_sdk.cli import main


def test_cli_init_and_validate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # 1. Run `appmanager-sdk init`
    res = main(["init", "--name", "Metrics Service", "--out", "app.py"])
    assert res == 0
    assert (tmp_path / "app.py").exists()

    # 2. Run `appmanager-sdk generate`
    res = main(["generate", "app:manifest", "--out", "manifest.json"])
    assert res == 0
    assert (tmp_path / "manifest.json").exists()

    # 3. Run `appmanager-sdk validate`
    res = main(["validate", "manifest.json"])
    assert res == 0

    # 4. Run `appmanager-sdk validate` on non-existent file
    assert main(["validate", "non_existent.json"]) == 1

    # 5. Run `appmanager-sdk generate` on non-existent target
    assert main(["generate", "non_existent_module:manifest"]) == 1

    # 6. Run invalid subcommand
    import pytest

    with pytest.raises(SystemExit):
        main(["unknown_cmd"])
