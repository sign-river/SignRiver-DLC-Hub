from __future__ import annotations

import json

import pytest

from signriver_publisher.github import (
    GitHubPublisherError,
    GitHubReleaseClient,
    GitHubRepository,
    GitHubRelease,
    GitHubUploadPaused,
)


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


class _Opener:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = payloads
        self.requests = []

    def __call__(self, request, *, timeout: int):
        self.requests.append((request, timeout))
        return _Response(self.payloads.pop(0))


def test_github_client_creates_public_repository_for_authenticated_user() -> None:
    opener = _Opener(
        [
            {"login": "sign-river"},
            {
                "name": "signriver-dlc-assets",
                "owner": {"login": "sign-river"},
            },
        ]
    )
    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "signriver-dlc-assets"),
        "token",
        api_base="https://api.example.test",
        opener=opener,
    )

    repository = client.create_repository("Release assets")

    assert repository == GitHubRepository("sign-river", "signriver-dlc-assets")
    user_request, create_request = (item[0] for item in opener.requests)
    assert user_request.get_method() == "GET"
    assert user_request.full_url == "https://api.example.test/user"
    assert create_request.get_method() == "POST"
    assert create_request.full_url == "https://api.example.test/user/repos"
    assert json.loads(create_request.data) == {
        "name": "signriver-dlc-assets",
        "description": "Release assets",
        "private": False,
        "has_issues": False,
        "has_projects": False,
        "has_wiki": False,
        "auto_init": True,
    }


def test_github_client_creates_repository_in_selected_organization() -> None:
    opener = _Opener(
        [
            {"login": "publisher-user"},
            {"name": "assets", "owner": {"login": "sign-river"}},
        ]
    )
    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"),
        "token",
        api_base="https://api.example.test",
        opener=opener,
    )

    client.create_repository("Release assets")

    assert opener.requests[1][0].full_url == (
        "https://api.example.test/orgs/sign-river/repos"
    )


def test_github_client_initializes_empty_repository_before_creating_release(
    monkeypatch,
) -> None:
    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"),
        "token",
        api_base="https://api.example.test",
    )
    calls = []

    def request(method, url, *, body=None, expect_json=True):
        calls.append((method, url, body, expect_json))
        if len(calls) == 1:
            raise GitHubPublisherError("GitHub API HTTP 422: Repository is empty")
        if len(calls) == 2:
            return {}
        return {
            "id": 4,
            "tag_name": "cities_skylines",
            "upload_url": "https://uploads.example.test/releases/4{?name,label}",
            "assets": [],
        }

    monkeypatch.setattr(client, "get_release_by_tag", lambda _tag: None)
    monkeypatch.setattr(client, "_request_json", request)

    release = client.ensure_release("cities_skylines")

    assert release.release_id == 4
    assert [call[0] for call in calls] == ["POST", "PUT", "POST"]
    assert calls[1][1].endswith("/repos/sign-river/assets/contents/README.md")
    assert calls[1][2]["message"] == "Initialize release repository"


def test_github_asset_upload_reports_streaming_progress(tmp_path) -> None:
    path = tmp_path / "asset.zip"
    path.write_bytes(b"x" * (2 * 1024 * 1024 + 5))
    observed = []

    def opener(request, *, timeout: int):
        assert request.get_header("Content-length") == str(path.stat().st_size)
        assert b"".join(request.data) == path.read_bytes()
        return _Response({"id": 8, "name": "asset.zip"})

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    release = GitHubRelease(1, "tag", "https://uploads.example.test/1{?name}", ())

    client.upload_asset(release, path, progress=lambda sent, size: observed.append((sent, size)))

    assert observed[0] == (0, path.stat().st_size)
    assert observed[-1] == (path.stat().st_size, path.stat().st_size)
    assert len(observed) == 4


def test_github_asset_upload_can_be_paused_between_chunks(tmp_path) -> None:
    path = tmp_path / "asset.zip"
    path.write_bytes(b"x" * (2 * 1024 * 1024))
    pause = {"requested": False}

    def progress(sent: int, _size: int) -> None:
        if sent:
            pause["requested"] = True

    def opener(request, *, timeout: int):
        b"".join(request.data)
        raise AssertionError("paused upload must not reach a response")

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    release = GitHubRelease(1, "tag", "https://uploads.example.test/1{?name}", ())

    with pytest.raises(GitHubUploadPaused):
        client.upload_asset(
            release,
            path,
            progress=progress,
            should_pause=lambda: pause["requested"],
        )
