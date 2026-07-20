from __future__ import annotations

import json

from signriver_app.infrastructure.catalog import (
    GitHubReleaseSource,
    GitHubSourceConfig,
    create_release_source,
    resolve_repository,
    speed_test_url,
)


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
