import json

import pytest

from signriver_publisher.updates import (
    UPDATE_MANIFEST_ASSET,
    UPDATE_RELEASE_TAG,
    UpdateReleaseDraft,
    release_asset_url,
    write_update_manifest,
)


def test_update_manifest_describes_verified_package_with_release_urls(tmp_path) -> None:
    package = tmp_path / "hub-module-v0.2.0.zip"
    package.write_bytes(b"verified package")
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
    assert payload["releases"][0]["size"] == len(b"verified package")
    assert len(payload["releases"][0]["sha256"]) == 64


def test_update_release_urls_are_stable_per_target() -> None:
    assert UPDATE_RELEASE_TAG == "updates"
    assert release_asset_url("gitlink", "signriver", "hub-assets", "a.zip") == (
        "https://gitlink.org.cn/signriver/hub-assets/releases/download/updates/a.zip"
    )


def test_update_release_rejects_invalid_versions_before_upload(tmp_path) -> None:
    package = tmp_path / "module.zip"
    package.write_bytes(b"package")

    with pytest.raises(ValueError, match="semantic"):
        UpdateReleaseDraft("next", "module", package)
