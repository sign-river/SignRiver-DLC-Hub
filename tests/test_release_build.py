import json

from tools.build_release import application_hidden_imports, write_release_manifest


def test_release_build_analyzes_external_application_dependencies() -> None:
    imports = application_hidden_imports()
    assert "webbrowser" in imports
    assert "signriver_app.infrastructure.persistence.database" in imports
    assert "signriver_app.infrastructure.installs.engine" in imports
    assert "signriver_app.application.download_queue" in imports


def test_full_release_manifest_excludes_user_state(tmp_path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "app" / "state.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "update.json").write_text("{}", encoding="utf-8")
    (tmp_path / "launcher.exe").write_bytes(b"launcher")
    manifest = json.loads(write_release_manifest(tmp_path, "0.2.0").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.0"
    assert [item["path"] for item in manifest["files"]] == ["launcher.exe"]
