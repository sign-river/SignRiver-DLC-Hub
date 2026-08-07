import json
import zipfile

import pytest

from signriver_publisher.updates import (
    UPDATE_MANIFEST_ASSET,
    UPDATE_RELEASE_TAG,
    UpdateReleaseDraft,
    inspect_module_archive,
    inspect_update_package,
    release_asset_url,
    write_update_manifest,
)


def _module_package(path, version: str = "0.2.0") -> None:
    with zipfile.ZipFile(path, "w") as package:
        package.writestr(
            "module.json",
            json.dumps(
                {
                    "version": version,
                    "api_version": 1,
                    "entrypoint": "app_entry.py:create_application",
                }
            ),
        )
        package.writestr("app_entry.py", "def create_application(context): pass")


def test_update_manifest_describes_verified_package_with_release_urls(tmp_path) -> None:
    package = tmp_path / "hub-module-v0.2.0.zip"
    _module_package(package)
    draft = UpdateReleaseDraft("0.2.0", "module", package, notes="Fix cache")
    url = release_asset_url("github", "sign-river", "hub-assets", package.name)
    manifest = write_update_manifest(
        tmp_path / UPDATE_MANIFEST_ASSET,
        channel="stable",
        releases=[draft.release_dict(url)],
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["channel"] == "stable"
    assert payload["releases"][0]["package_url"] == url
    assert payload["releases"][0]["size"] == package.stat().st_size
    assert len(payload["releases"][0]["sha256"]) == 64


def test_update_release_urls_are_stable_per_target() -> None:
    assert UPDATE_RELEASE_TAG == "updates"
    assert release_asset_url("gitlink", "signriver", "hub-assets", "a.zip") == (
        "https://gitlink.org.cn/signriver/hub-assets/releases/download/updates/a.zip"
    )


def test_update_package_identity_is_read_from_module_metadata(tmp_path) -> None:
    package = tmp_path / "hub-module-v0.2.0-windows-x64.zip"
    _module_package(package)

    info = inspect_update_package(package)

    assert (info.version, info.kind) == ("0.2.0", "module")


def test_module_archive_identity_is_read_from_module_metadata(tmp_path) -> None:
    package = tmp_path / "SignRiver-DLC-Hub-module-v0.2.0.zip"
    _module_package(package)

    info = inspect_module_archive(package)

    assert info.version == "0.2.0"


def test_module_archive_rejects_full_update_package(tmp_path) -> None:
    package = tmp_path / "hub-full-v0.3.0.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "release-manifest.json",
            json.dumps({"schema_version": 1, "version": "0.3.0", "files": []}),
        )

    with pytest.raises(ValueError, match="模块归档"):
        inspect_module_archive(package)


def test_update_package_identity_is_read_from_full_metadata(tmp_path) -> None:
    package = tmp_path / "hub-full-v0.3.0-windows-x64.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "release-manifest.json",
            json.dumps(
                {"schema_version": 1, "version": "0.3.0", "files": []}
            ),
        )

    info = inspect_update_package(package)

    assert (info.version, info.kind) == ("0.3.0", "full")


def test_update_package_rejects_filename_metadata_mismatch(tmp_path) -> None:
    package = tmp_path / "hub-full-v0.9.0-windows-x64.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "release-manifest.json",
            json.dumps(
                {"schema_version": 1, "version": "0.3.0", "files": []}
            ),
        )

    with pytest.raises(ValueError, match="filename"):
        inspect_update_package(package)


def test_update_release_rejects_invalid_versions_before_upload(tmp_path) -> None:
    package = tmp_path / "module.zip"
    _module_package(package)

    with pytest.raises(ValueError, match="semantic"):
        UpdateReleaseDraft("next", "module", package)


def test_update_release_rejects_wrapped_installer_zip_for_full_update(
    tmp_path,
) -> None:
    package = tmp_path / "installer.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            "Product/release-manifest.json",
            json.dumps({"schema_version": 1, "version": "0.2.0", "files": []}),
        )

    with pytest.raises(ValueError, match="at its root"):
        UpdateReleaseDraft("0.2.0", "full", package)
