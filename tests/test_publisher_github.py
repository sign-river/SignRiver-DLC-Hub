from __future__ import annotations

import json
from io import BytesIO
import socket
import urllib.error

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


def test_github_client_ensure_repository_reuses_existing_target(monkeypatch) -> None:
    client = GitHubReleaseClient(GitHubRepository("sign-river", "assets"), "token")
    calls: list[str] = []
    monkeypatch.setattr(client, "repository_info", lambda: {"name": "assets"})
    monkeypatch.setattr(
        client,
        "create_repository",
        lambda _description: calls.append("create") or client.repository,
    )

    assert client.ensure_repository("Release assets") == client.repository
    assert calls == []


def test_github_client_ensure_repository_creates_missing_target(monkeypatch) -> None:
    client = GitHubReleaseClient(GitHubRepository("sign-river", "assets"), "token")
    calls: list[str] = []

    def missing() -> dict[str, object]:
        raise GitHubPublisherError("GitHub API HTTP 404: Not Found")

    monkeypatch.setattr(client, "repository_info", missing)
    monkeypatch.setattr(
        client,
        "create_repository",
        lambda description: calls.append(description) or client.repository,
    )

    assert client.ensure_repository("Release assets") == client.repository
    assert calls == ["Release assets"]


def test_github_client_removes_assets_absent_from_local_snapshot(monkeypatch) -> None:
    client = GitHubReleaseClient(GitHubRepository("sign-river", "assets"), "token")
    release = GitHubRelease(
        4,
        "guides",
        "https://uploads.example.test/4{?name}",
        (
            {"id": 10, "name": "guides_index.json"},
            {"id": 11, "name": "old-guide.json"},
        ),
    )
    deleted: list[int] = []
    monkeypatch.setattr(client, "delete_asset", lambda asset_id: deleted.append(asset_id))

    removed = client.delete_assets_not_in_release(release, {"guides_index.json"})

    assert removed == ("old-guide.json",)
    assert deleted == [11]


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
    # 256 KiB chunks keep a requested safe pause responsive during uploads.
    assert len(observed) == 10


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


def test_github_asset_upload_retries_after_connection_reset(tmp_path, monkeypatch) -> None:
    path = tmp_path / "asset.zip"
    path.write_bytes(b"asset")
    attempts = []

    def opener(request, *, timeout: int):
        attempts.append(b"".join(request.data))
        if len(attempts) == 1:
            raise OSError(10054, "connection reset")
        return _Response({"id": 8, "name": "asset.zip"})

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    monkeypatch.setattr(client, "_remove_partial_asset", lambda *_args: None)
    monkeypatch.setattr(client, "_uploaded_asset_if_present", lambda *_args: None)
    monkeypatch.setattr("signriver_publisher.github.time.sleep", lambda _seconds: None)
    release = GitHubRelease(1, "tag", "https://uploads.example.test/1{?name}", ())

    client.upload_asset(release, path)

    assert attempts == [b"asset", b"asset"]


def test_github_asset_upload_recovers_from_existing_asset_conflict(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "asset.zip"
    path.write_bytes(b"asset")
    attempts = []

    def opener(request, *, timeout: int):
        attempts.append(b"".join(request.data))
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                request.full_url,
                422,
                "Validation Failed",
                None,
                BytesIO(b'{"errors":[{"code":"already_exists"}]}'),
            )
        return _Response({"id": 8, "name": "asset.zip"})

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    monkeypatch.setattr(client, "_remove_partial_asset", lambda *_args: None)
    monkeypatch.setattr(client, "_uploaded_asset_if_present", lambda *_args: None)
    monkeypatch.setattr("signriver_publisher.github.time.sleep", lambda _seconds: None)
    release = GitHubRelease(1, "tag", "https://uploads.example.test/1{?name}", ())

    client.upload_asset(release, path)

    assert attempts == [b"asset", b"asset"]


def test_github_asset_upload_retries_transient_server_error(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "asset.zip"
    path.write_bytes(b"asset")
    attempts = []

    def opener(request, *, timeout: int):
        attempts.append(b"".join(request.data))
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                request.full_url, 502, "Bad Gateway", None,
                BytesIO(b'{"message":"Server Error"}'),
            )
        return _Response({"id": 8, "name": "asset.zip"})

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    monkeypatch.setattr(client, "_remove_partial_asset", lambda *_args: None)
    monkeypatch.setattr(client, "_uploaded_asset_if_present", lambda *_args: None)
    monkeypatch.setattr("signriver_publisher.github.time.sleep", lambda _seconds: None)
    release = GitHubRelease(1, "tag", "https://uploads.example.test/1{?name}", ())

    client.upload_asset(release, path)

    assert attempts == [b"asset", b"asset"]


def test_github_api_get_retries_transient_server_error(monkeypatch) -> None:
    attempts = []

    def opener(request, *, timeout: int):
        attempts.append(request.get_method())
        if len(attempts) == 1:
            raise urllib.error.HTTPError(
                request.full_url, 502, "Bad Gateway", None,
                BytesIO(b'{"message":"Server Error"}'),
            )
        return _Response({
            "id": 1,
            "tag_name": "rimworld",
            "assets": [],
            "upload_url": "https://uploads.example.test/1{?name}",
        })

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    monkeypatch.setattr("signriver_publisher.github.time.sleep", lambda _seconds: None)

    release = client.get_release_by_tag("rimworld")

    assert release is not None
    assert attempts == ["GET", "GET"]


def test_github_asset_upload_recovers_when_success_response_is_lost(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "asset.zip"
    path.write_bytes(b"asset")
    release = GitHubRelease(1, "tag", "https://uploads.example.test/1{?name}", ())
    attempts = []

    def opener(request, *, timeout: int):
        attempts.append((request.get_method(), timeout))
        raise socket.timeout("The read operation timed out")

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    monkeypatch.setattr(
        client,
        "get_release_by_tag",
        lambda _tag: GitHubRelease(
            1,
            "tag",
            release.upload_url,
            ({"id": 7, "name": path.name, "size": path.stat().st_size},),
        ),
    )

    result = client.upload_asset(release, path)

    assert result["id"] == 7
    assert attempts == [("POST", 20)]


def test_github_api_get_retries_a_response_read_timeout(monkeypatch) -> None:
    attempts = []

    class _TimeoutResponse(_Response):
        def read(self) -> bytes:
            raise socket.timeout("The read operation timed out")

    def opener(request, *, timeout: int):
        attempts.append((request.get_method(), timeout))
        if len(attempts) < 3:
            return _TimeoutResponse({})
        return _Response({"name": "assets"})

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    monkeypatch.setattr("signriver_publisher.github.time.sleep", lambda _seconds: None)

    assert client.repository_info() == {"name": "assets"}
    assert attempts == [("GET", 12), ("GET", 12), ("GET", 12)]


def test_github_api_get_reports_persistent_read_timeout_without_connection_error(
    monkeypatch,
) -> None:
    class _TimeoutResponse(_Response):
        def read(self) -> bytes:
            raise socket.timeout("The read operation timed out")

    def opener(_request, *, timeout: int):
        assert timeout == 12
        return _TimeoutResponse({})

    client = GitHubReleaseClient(
        GitHubRepository("sign-river", "assets"), "token", opener=opener
    )
    monkeypatch.setattr("signriver_publisher.github.time.sleep", lambda _seconds: None)

    with pytest.raises(GitHubPublisherError, match="读取超时.*重试 3 次") as raised:
        client.repository_info()

    assert "连接失败" not in str(raised.value)
