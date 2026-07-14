from __future__ import annotations

import json
from types import SimpleNamespace
import zipfile
from pathlib import Path

import pytest

from signriver_publisher import GameProfile, PublisherSettings, PublisherWorkspace, SteamAppInfo, SteamDlc, SteamStoreClient, WorkspaceError, discover_settings_path, generate_cream_api_ini, load_steam_appinfo
from signriver_publisher.gitlink import GitLinkAttachmentClient, GitLinkCli, GitLinkRepository, find_release_id
from signriver_publisher.gitlink import GitLinkError
from signriver_publisher.remote import RemoteResourceManager, parse_release


def sample_appinfo(app_id: str = "281990") -> SteamAppInfo:
    return SteamAppInfo(
        app_id,
        "Stellaris",
        "2026-06-15 21:07:12",
        (SteamDlc("498870", "Stellaris: Plantoids Species Pack"),),
    )


def test_initializes_stellaris_workspace(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")

    profile = workspace.initialize()

    assert profile == GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990")
    assert (workspace.game_dir("stellaris") / "dlc").is_dir()
    assert (workspace.game_dir("stellaris") / "patches").is_dir()


def test_other_game_uses_its_own_appinfo_name_and_output_directory(tmp_path: Path) -> None:
    def provider(app_id: str) -> SteamAppInfo:
        return SteamAppInfo(app_id, "Europa Universalis IV", "2026-07-14", ())

    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=provider)
    workspace.initialize()
    profile = GameProfile.create("europa_universalis_4", "Europa Universalis IV", "236850")
    workspace.save_game(profile)

    workspace.refresh_appinfo(profile)

    assert profile.appinfo_name == "europa_universalis_4_appinfo.json"
    assert (workspace.output_dir / "europa_universalis_4" / profile.appinfo_name).is_file()
    assert not (workspace.output_dir / "stellaris" / profile.appinfo_name).exists()


def test_rejects_appinfo_name_that_does_not_match_game_id(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")

    with pytest.raises(WorkspaceError, match="other_game_appinfo.json"):
        workspace.save_game(GameProfile("other_game", "Other Game", "other_game", "stellaris_appinfo.json", "123"))


def test_legacy_stellaris_profile_gets_steam_app_id(tmp_path: Path) -> None:
    game = tmp_path / "publisher" / "games" / "stellaris"
    game.mkdir(parents=True)
    (game / "game.json").write_text(json.dumps({"game_id": "stellaris", "display_name": "Stellaris", "release_tag": "stellaris", "appinfo_name": "stellaris_appinfo.json"}), encoding="utf-8")

    profile = PublisherWorkspace(tmp_path / "publisher").initialize()

    assert profile.steam_app_id == "281990"


def test_builds_each_dlc_and_patch_and_generates_appinfo(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    game = workspace.game_dir(profile.game_id)
    dlc = game / "dlc" / "dlc001_symbols_of_domination"
    dlc.mkdir()
    (dlc / "dlc001.dlc").write_text('name="Symbols of Domination"', encoding="utf-8")
    (dlc / "dlc001.zip").write_bytes(b"nested archive")
    patches = game / "patches"
    (patches / "steam_api64.dll").write_bytes(b"patched dll")
    (patches / "steam_api64_o.dll").write_bytes(b"original dll")
    appinfo_payload = {
        "app_id": "281990",
        "name": "Stellaris",
        "update_time": "2026-06-15 21:07:12",
        "dlcs": [{"id": "498870", "name": "Stellaris: Plantoids Species Pack"}],
    }
    (patches / "unlock_patch.txt").write_text("patch", encoding="utf-8")

    records = workspace.build(profile)

    assert [record.asset_name for record in records] == [
        "dlc001_symbols_of_domination.zip",
        "stellaris_appinfo.json",
        "steam_api64.dll",
        "steam_api64_o.dll",
        "unlock_patch.txt",
    ]
    package = workspace.output_dir / "stellaris" / "dlc001_symbols_of_domination.zip"
    with zipfile.ZipFile(package) as archive:
        assert archive.namelist() == [
            "dlc001_symbols_of_domination/dlc001.dlc",
            "dlc001_symbols_of_domination/dlc001.zip",
        ]
        assert all(item.compress_type == zipfile.ZIP_DEFLATED for item in archive.infolist())
    appinfo = json.loads((workspace.output_dir / "stellaris" / "stellaris_appinfo.json").read_text(encoding="utf-8"))
    assert appinfo == appinfo_payload


def test_rebuild_removes_stale_output(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=sample_appinfo)
    profile = workspace.initialize()
    output = workspace.output_dir / profile.game_id
    output.mkdir(parents=True)
    (output / "old.zip").write_bytes(b"old")
    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"new")
    (patches / "steam_api64_o.dll").write_bytes(b"old")

    workspace.build(profile)

    assert not (output / "old.zip").exists()
    assert (output / profile.appinfo_name).is_file()


def test_import_and_remove_are_restricted_to_resource_root(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = workspace.initialize()
    source = tmp_path / "dlc002_arachnoid"
    source.mkdir()
    (source / "dlc002.dlc").write_text("x", encoding="utf-8")

    imported = workspace.import_dlc(profile, source)
    workspace.remove_source(profile, "dlc", imported.name)

    assert not imported.exists()
    with pytest.raises(WorkspaceError):
        workspace.remove_source(profile, "dlc", "../game.json")


def test_rejects_invalid_dlc_folder_and_symlink(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher")
    profile = workspace.initialize()
    invalid = workspace.game_dir(profile.game_id) / "dlc" / "random"
    invalid.mkdir()
    (invalid / "file.txt").write_text("x", encoding="utf-8")

    with pytest.raises(WorkspaceError, match="dlc001"):
        workspace.build(profile)


def test_appinfo_generates_expected_cream_api_ini(tmp_path: Path) -> None:
    path = tmp_path / "stellaris_appinfo.json"
    path.write_text(
        json.dumps(
            {
                "app_id": "281990",
                "name": "Stellaris",
                "update_time": "2026-06-15 21:07:12",
                "dlcs": [
                    {"id": "498870", "name": "Stellaris: Plantoids Species Pack"},
                    {"id": "518910", "name": "Stellaris: Leviathans Story Pack"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = generate_cream_api_ini(load_steam_appinfo(path, expected_app_id="281990"))

    assert result == (
        "[steam]\n"
        "appid = 281990\n"
        "language = schinese\n"
        "unlockall = True\n"
        "extraprotection = False\n"
        "forceoffline = False\n"
        "\n"
        "[dlc]\n"
        "498870 = Stellaris: Plantoids Species Pack\n"
        "518910 = Stellaris: Leviathans Story Pack\n"
    )


def test_build_requires_dlls_and_rejects_wrong_steam_app(tmp_path: Path) -> None:
    workspace = PublisherWorkspace(tmp_path / "publisher", appinfo_provider=lambda _app_id: sample_appinfo("123"))
    profile = workspace.initialize()

    with pytest.raises(WorkspaceError, match="steam_api64.dll"):
        workspace.build(profile)

    patches = workspace.game_dir(profile.game_id) / "patches"
    (patches / "steam_api64.dll").write_bytes(b"patched")
    (patches / "steam_api64_o.dll").write_bytes(b"original")
    with pytest.raises(WorkspaceError, match="当前游戏要求 281990"):
        workspace.build(profile)


def test_steam_store_client_combines_names_and_sorts_ids() -> None:
    def fetch(url: str, _timeout: float, _limit: int) -> bytes:
        if "/api/appdetails" in url:
            return json.dumps({"281990": {"success": True, "data": {"name": "Stellaris", "dlc": [20, 10]}}}).encode()
        if "/api/dlcforapp/" in url:
            return json.dumps({"status": 1, "appid": 281990, "name": "Stellaris", "dlc": [{"id": 10, "name": "First"}, {"id": 20, "name": "Second"}]}).encode()
        raise AssertionError(url)

    result = SteamStoreClient(fetch=fetch).fetch_appinfo("281990")

    assert result.app_id == "281990"
    assert result.name == "Stellaris"
    assert [(item.app_id, item.name) for item in result.dlcs] == [("10", "First"), ("20", "Second")]


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"data": {"releases": [{"id": 7, "tag_name": "stellaris"}]}}, "7"),
        ({"releases": [{"version_gid": "abc", "tag_name": "stellaris"}]}, "abc"),
        ({"data": {"releases": [{"id": 7, "tag_name": "other"}]}}, None),
    ],
)
def test_find_release_id_handles_cli_response_shapes(payload: dict[str, object], expected: str | None) -> None:
    assert find_release_id(payload, "stellaris") == expected


def test_attachment_upload_streams_file_and_returns_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "dlc001.zip"
    source.write_bytes(b"package-data")

    class Response:
        status = 200

        @staticmethod
        def read(_limit: int) -> bytes:
            return b'{"id":"attachment-123"}'

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.headers: dict[str, str] = {}
            self.sent = bytearray()

        def putrequest(self, *_args) -> None: pass
        def putheader(self, name: str, value: str) -> None: self.headers[name] = value
        def endheaders(self) -> None: pass
        def send(self, value: bytes) -> None: self.sent.extend(value)
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    attachment_id = GitLinkAttachmentClient("secret-token").upload(source)

    assert attachment_id == "attachment-123"
    assert Connection.instance.headers["Authorization"] == "Bearer secret-token"
    assert b"package-data" in Connection.instance.sent


def test_cli_uses_temporary_token_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["environment"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout='{"data":{"releases":[]}}', stderr="")

    monkeypatch.setattr("signriver_publisher.gitlink.subprocess.run", fake_run)
    GitLinkCli("gitlink-cli").list_releases(GitLinkRepository(), token="temporary-token")

    assert captured["environment"]["GITLINK_TOKEN"] == "temporary-token"  # type: ignore[index]
    assert "temporary-token" not in captured["command"]  # type: ignore[operator]


def test_release_api_uses_bearer_token_without_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        @staticmethod
        def read(_limit: int) -> bytes:
            return b'{"releases":[]}'

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.request_args = None

        def request(self, *args, **kwargs) -> None: self.request_args = (args, kwargs)
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    result = GitLinkAttachmentClient("secret-token").list_releases(GitLinkRepository())

    assert result == {"releases": []}
    args, kwargs = Connection.instance.request_args
    assert args[:2] == ("GET", "/api/signriver/signriver-dlc-assets/releases.json?page=1&limit=100")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


def test_attachment_delete_accepts_empty_success_response(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 204

        @staticmethod
        def read(_limit: int) -> bytes:
            return b""

    class Connection:
        instance: "Connection"

        def __init__(self, *_args, **_kwargs) -> None:
            Connection.instance = self
            self.request_args = None

        def request(self, *args, **kwargs) -> None: self.request_args = (args, kwargs)
        def getresponse(self) -> Response: return Response()
        def close(self) -> None: pass

    monkeypatch.setattr("signriver_publisher.gitlink.http.client.HTTPSConnection", Connection)

    GitLinkAttachmentClient("secret-token").delete_attachment("attachment-123")

    args, kwargs = Connection.instance.request_args
    assert args[:2] == ("DELETE", "/api/attachments/attachment-123.json")
    assert kwargs["headers"]["Authorization"] == "Bearer secret-token"


def test_publisher_settings_loads_private_config(tmp_path: Path) -> None:
    path = tmp_path / "publisher.local.json"
    path.write_text(
        json.dumps({"gitlink": {"owner": "owner", "repository": "assets", "token": "local-secret"}}),
        encoding="utf-8",
    )

    settings = PublisherSettings.load(path)

    assert settings == PublisherSettings("owner", "assets", "local-secret")


def test_settings_path_honors_environment_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "private.json"
    monkeypatch.setenv("SIGNRIVER_PUBLISHER_CONFIG", str(path))

    assert discover_settings_path() == path.resolve()


def test_parse_remote_release_assets() -> None:
    payload = {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "body": "body", "attachments": [{"id": 1, "title": "a.zip", "filesize": "1 MB", "url": "/a"}]}]}

    release = parse_release(payload, "stellaris")

    assert release is not None
    assert release.release_id == "9"
    assert [(item.asset_id, item.name, item.display_size) for item in release.assets] == [("1", "a.zip", "1 MB")]


def test_remote_upload_replaces_same_name_and_keeps_other_assets(tmp_path: Path) -> None:
    source = tmp_path / "same.zip"
    source.write_bytes(b"new")

    class Client:
        deleted: list[str] = []
        updated_ids: list[str] = []

        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "body": "body", "attachments": [{"id": "old", "title": "same.zip"}, {"id": "keep", "title": "other.zip"}]}]}
        def upload(self, _path): return "new"
        def update_release(self, _repo, **kwargs): self.updated_ids = kwargs["attachment_ids"]
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    result = RemoteResourceManager(client, GitLinkRepository()).upload_file(GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990"), source)

    assert result.action == "替换"
    assert client.updated_ids == ["keep", "new"]
    assert client.deleted == ["old"]


def test_remote_delete_can_remove_last_release_asset() -> None:
    class Client:
        deleted: list[str] = []
        updated_ids: list[str] | None = None

        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "attachments": [{"id": "only", "title": "only.zip"}]}]}
        def update_release(self, _repo, **kwargs): self.updated_ids = kwargs["attachment_ids"]
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    result = RemoteResourceManager(client, GitLinkRepository()).delete_asset(GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990"), "only")

    assert result.action == "删除"
    assert client.updated_ids == []
    assert client.deleted == ["only"]


def test_remote_upload_cleans_new_attachment_if_release_update_fails(tmp_path: Path) -> None:
    source = tmp_path / "new.zip"
    source.write_bytes(b"new")

    class Client:
        deleted: list[str] = []

        def list_releases(self, _repo):
            return {"releases": [{"id": 9, "tag_name": "stellaris", "name": "Stellaris", "attachments": []}]}
        def upload(self, _path): return "orphan"
        def update_release(self, _repo, **_kwargs): raise GitLinkError("update failed")
        def delete_attachment(self, value): self.deleted.append(value)

    client = Client()
    with pytest.raises(GitLinkError, match="update failed"):
        RemoteResourceManager(client, GitLinkRepository()).upload_file(GameProfile("stellaris", "Stellaris", "stellaris", "stellaris_appinfo.json", "281990"), source)

    assert client.deleted == ["orphan"]
