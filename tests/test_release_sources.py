from __future__ import annotations

import json

from signriver_app.infrastructure.catalog import (
    GitHubReleaseSource,
    GitHubSourceConfig,
    create_release_source,
    resolve_repository,
    speed_test_url,
    StaticManifestReleaseSource,
)
from signriver_app.infrastructure.catalog.gitlink import ReleaseSourceError


def test_github_release_source_normalizes_assets() -> None:
    payload = [
        {
            "id": 11,
            "tag_name": "stellaris",
            "name": "Stellaris",
            "body": "assets",
            "assets": [
                {
                    "id": 99,
                    "name": "dlc001_demo.zip",
                    "browser_download_url": (
                        "https://github.com/sign-river/signriver-dlc-assets/"
                        "releases/download/stellaris/dlc001_demo.zip"
                    ),
                    "size": 2048,
                }
            ],
        }
    ]

    def fetch(url: str, _timeout: float, _limit: int) -> bytes:
        assert "api.github.com" in url
        if "/releases/tags/" in url:
            return json.dumps(payload[0]).encode("utf-8")
        return json.dumps(payload).encode("utf-8")

    source = GitHubReleaseSource(
        GitHubSourceConfig("sign-river", "signriver-dlc-assets"),
        fetch=fetch,
    )
    release = source.get_release_by_tag("stellaris")
    assert release.tag == "stellaris"
    assert release.assets[0].name == "dlc001_demo.zip"
    assert release.assets[0].size_bytes == 2048


def test_resolve_repository_remaps_gitlink_owner_for_github() -> None:
    owner, repo = resolve_repository(
        "github",
        owner="signriver",
        repository="signriver-dlc-assets",
    )
    assert owner == "sign-river"
    assert repo == "signriver-dlc-assets"


def test_factory_and_speed_urls_follow_provider() -> None:
    gitlink = create_release_source("gitlink", "signriver", "signriver-dlc-assets")
    github = create_release_source("github", "sign-river", "signriver-dlc-assets")
    assert gitlink.__class__.__name__ == "GitLinkReleaseSource"
    assert github.__class__.__name__ == "GitHubReleaseSource"
    assert speed_test_url("gitlink").endswith("/test/test.bin")
    assert "github.com/sign-river/" in speed_test_url("github")


class _FailingLegacySource:
    def get_release_by_tag(self, _tag: str):
        raise ReleaseSourceError("API rate limited")


def test_static_manifest_avoids_api_and_builds_direct_asset_urls(tmp_path) -> None:
    payload = json.dumps({
        "schema_version": 1,
        "release_tag": "cities_skylines",
        "assets": [{
            "name": "dlc001_demo.zip",
            "size_bytes": 2048,
            "sha256": "a" * 64,
        }],
    }).encode("utf-8")
    cache = tmp_path / "github" / "cities_skylines.json"
    source = StaticManifestReleaseSource(
        "github", "sign-river", "signriver-dlc-assets",
        legacy_source=_FailingLegacySource(), cache_path=cache,
        fetch=lambda *_args: payload,
    )

    release = source.get_release_by_tag("cities_skylines")

    assert release.assets[0].asset_id == "a" * 64
    assert release.assets[0].download_url == (
        "https://github.com/sign-river/signriver-dlc-assets/releases/download/"
        "cities_skylines/dlc001_demo.zip"
    )
    assert cache.read_bytes() == payload


def test_static_manifest_uses_provider_scoped_cache_when_remote_and_api_fail(
    tmp_path,
) -> None:
    payload = json.dumps({
        "schema_version": 1,
        "release_tag": "stellaris",
        "assets": [{"name": "dlc001_demo.zip", "size_bytes": 10}],
    }).encode("utf-8")
    cache = tmp_path / "gitlink" / "stellaris.json"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(payload)
    source = StaticManifestReleaseSource(
        "gitlink", "signriver", "signriver-dlc-assets",
        legacy_source=_FailingLegacySource(), cache_path=cache,
        fetch=lambda *_args: (_ for _ in ()).throw(OSError("offline")),
    )

    release = source.get_release_by_tag("stellaris")

    assert release.assets[0].download_url.startswith("https://gitlink.org.cn/")
