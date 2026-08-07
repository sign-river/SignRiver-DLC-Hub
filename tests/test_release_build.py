import json
import zipfile

from tools.build_release import (
    application_hidden_imports,
    build_full_update_archive,
    write_release_manifest,
)


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
    (tmp_path / "config" / "publisher.local.json").write_text(
        '{"token": "private"}', encoding="utf-8"
    )
    (tmp_path / "launcher.exe").write_bytes(b"launcher")
    manifest = json.loads(write_release_manifest(tmp_path, "0.2.0").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.0"
    assert [item["path"] for item in manifest["files"]] == ["launcher.exe"]


def test_full_update_archive_is_flat_and_contains_only_managed_files(
    tmp_path,
) -> None:
    release = tmp_path / "release"
    (release / "app").mkdir(parents=True)
    (release / "config").mkdir()
    (release / "app" / "managed.txt").write_text("managed", encoding="utf-8")
    (release / "app" / "state.json").write_text("{}", encoding="utf-8")
    (release / "config" / "update.json").write_text("{}", encoding="utf-8")
    write_release_manifest(release, "0.2.0")

    archive = build_full_update_archive(
        release, tmp_path / "full-v0.2.0.zip", "0.2.0"
    )

    with zipfile.ZipFile(archive) as package:
        assert package.namelist() == [
            "release-manifest.json",
            "app/managed.txt",
        ]
