from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .cream import SteamAppInfo
from .models import GameProfile, ResourceRecord
from .steam import SteamApiError, SteamStoreClient

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_DLC_DIR = re.compile(r"^(dlc\d{3,})_([A-Za-z0-9][A-Za-z0-9_-]*)$", re.I)


class WorkspaceError(RuntimeError):
    pass


class PublisherWorkspace:
    def __init__(self, root: Path, *, appinfo_provider=None) -> None:
        self.root = root.resolve()
        self.games_dir = self.root / "games"
        self.output_dir = self.root / "output"
        self._appinfo_provider = appinfo_provider or SteamStoreClient().fetch_appinfo

    def initialize(self) -> GameProfile:
        self.games_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        if not self.list_games():
            profile = GameProfile.create("stellaris", "Stellaris", "281990")
            self.save_game(profile)
            return profile
        return self.list_games()[0]

    def list_games(self) -> tuple[GameProfile, ...]:
        profiles: list[GameProfile] = []
        if not self.games_dir.exists():
            return ()
        for path in sorted(self.games_dir.glob("*/game.json")):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    profiles.append(GameProfile.from_dict(value))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return tuple(profiles)

    def save_game(self, profile: GameProfile) -> None:
        self._validate_profile(profile)
        game_dir = self.game_dir(profile.game_id)
        (game_dir / "dlc").mkdir(parents=True, exist_ok=True)
        (game_dir / "patches").mkdir(parents=True, exist_ok=True)
        path = game_dir / "game.json"
        self._atomic_json(path, profile.to_dict())

    def game_dir(self, game_id: str) -> Path:
        if not _SAFE_ID.fullmatch(game_id):
            raise WorkspaceError("游戏 ID 只能包含小写字母、数字、下划线和短横线")
        return self.games_dir / game_id

    def scan_sources(self, profile: GameProfile) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        game_dir = self.game_dir(profile.game_id)
        dlcs = tuple(sorted(path for path in (game_dir / "dlc").iterdir() if path.is_dir()))
        patches = tuple(sorted(path for path in (game_dir / "patches").iterdir()))
        return dlcs, patches

    def import_dlc(self, profile: GameProfile, source: Path) -> Path:
        source = source.resolve()
        if not source.is_dir():
            raise WorkspaceError("请选择一个 DLC 文件夹")
        self._parse_dlc_folder(source.name)
        destination = self.game_dir(profile.game_id) / "dlc" / source.name
        if destination.exists():
            raise WorkspaceError(f"DLC 已存在：{source.name}")
        shutil.copytree(source, destination)
        return destination

    def import_patch(self, profile: GameProfile, source: Path) -> Path:
        source = source.resolve()
        if not source.exists():
            raise WorkspaceError("补丁不存在")
        destination = self.game_dir(profile.game_id) / "patches" / source.name
        if destination.exists():
            raise WorkspaceError(f"补丁已存在：{source.name}")
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)
        return destination

    def remove_source(self, profile: GameProfile, kind: str, name: str) -> None:
        if kind not in {"dlc", "patches"}:
            raise WorkspaceError("未知资源类型")
        root = (self.game_dir(profile.game_id) / kind).resolve()
        target = (root / name).resolve()
        if target.parent != root or not target.exists():
            raise WorkspaceError("资源不存在或路径不安全")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()

    def build(self, profile: GameProfile) -> tuple[ResourceRecord, ...]:
        self._validate_profile(profile)
        dlcs, patches = self.scan_sources(profile)
        target = self.output_dir / profile.game_id
        target.mkdir(parents=True, exist_ok=True)
        records: list[ResourceRecord] = []
        expected: set[str] = set()

        for source in dlcs:
            dlc_id, display_name = self._parse_dlc_folder(source.name)
            asset_name = f"{source.name}.zip"
            output = target / asset_name
            self._zip_directory(source, output, include_root=True)
            records.append(self._record("dlc", dlc_id, display_name, source, output))
            expected.add(asset_name)

        patch_by_name = {path.name.lower(): path for path in patches}
        for dll_name in ("steam_api64.dll", "steam_api64_o.dll"):
            source = patch_by_name.get(dll_name)
            if source is None or not source.is_file():
                raise WorkspaceError(f"补丁目录缺少 {dll_name}")

        appinfo = self.refresh_appinfo(profile)
        appinfo_output = target / profile.appinfo_name
        records.append(self._record("appinfo", appinfo.app_id, appinfo.name, appinfo_output, appinfo_output))
        expected.add(profile.appinfo_name)

        for source in patches:
            if source.name.lower() in {profile.appinfo_name.lower(), "cream_api.ini"}:
                continue
            if source.is_symlink():
                raise WorkspaceError(f"不允许符号链接：{source.name}")
            if source.is_dir():
                asset_name = f"{source.name}.zip"
                output = target / asset_name
                self._zip_directory(source, output, include_root=True)
            elif source.is_file():
                asset_name = source.name
                output = target / asset_name
                shutil.copy2(source, output)
            else:
                continue
            records.append(self._record("patch", source.stem, source.stem.replace("_", " "), source, output))
            expected.add(asset_name)

        for stale in target.iterdir():
            if stale.is_file() and stale.name not in expected:
                stale.unlink()

        return tuple(records)

    def refresh_appinfo(self, profile: GameProfile) -> SteamAppInfo:
        self._validate_profile(profile)
        if not profile.steam_app_id:
            raise WorkspaceError("当前游戏没有配置 Steam App ID")
        try:
            appinfo = self._appinfo_provider(profile.steam_app_id)
        except SteamApiError as error:
            raise WorkspaceError(str(error)) from error
        if appinfo.app_id != profile.steam_app_id:
            raise WorkspaceError(f"Steam 返回的 App ID 是 {appinfo.app_id}，当前游戏要求 {profile.steam_app_id}")
        target = self.output_dir / profile.game_id / profile.appinfo_name
        self._atomic_json(
            target,
            {
                "app_id": appinfo.app_id,
                "name": appinfo.name,
                "update_time": appinfo.update_time,
                "dlcs": [{"id": item.app_id, "name": item.name} for item in appinfo.dlcs],
            },
        )
        return appinfo

    def publish_files(self, profile: GameProfile) -> tuple[Path, ...]:
        target = self.output_dir / profile.game_id
        appinfo = target / profile.appinfo_name
        if not appinfo.is_file():
            raise WorkspaceError("请先生成发布包")
        for name in ("steam_api64.dll", "steam_api64_o.dll"):
            if not (target / name).is_file():
                raise WorkspaceError(f"发布包缺少 {name}，请先生成全部发布文件")
        return tuple(sorted(path for path in target.iterdir() if path.is_file()))

    @staticmethod
    def _validate_profile(profile: GameProfile) -> None:
        if not _SAFE_ID.fullmatch(profile.game_id):
            raise WorkspaceError("游戏 ID 格式不正确")
        if not _SAFE_ID.fullmatch(profile.release_tag):
            raise WorkspaceError("Release 标签格式不正确")
        expected_appinfo_name = f"{profile.game_id}_appinfo.json"
        if profile.appinfo_name != expected_appinfo_name:
            raise WorkspaceError(f"AppInfo 文件名必须与游戏 ID 对应：{expected_appinfo_name}")
        if profile.steam_app_id and not profile.steam_app_id.isdigit():
            raise WorkspaceError("Steam App ID 必须是数字")

    @staticmethod
    def _parse_dlc_folder(name: str) -> tuple[str, str]:
        match = _DLC_DIR.fullmatch(name)
        if not match:
            raise WorkspaceError("DLC 文件夹应命名为 dlc001_英文名称")
        display = match.group(2).replace("_", " ").strip().title()
        return match.group(1).lower(), display

    @staticmethod
    def _zip_directory(source: Path, destination: Path, *, include_root: bool) -> None:
        files = sorted(path for path in source.rglob("*") if path.is_file())
        if not files:
            raise WorkspaceError(f"文件夹为空：{source.name}")
        if any(path.is_symlink() for path in source.rglob("*")):
            raise WorkspaceError(f"不允许符号链接：{source.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(delete=False, dir=destination.parent, suffix=".tmp") as handle:
            temporary = Path(handle.name)
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for path in files:
                    relative = path.relative_to(source)
                    arcname = Path(source.name) / relative if include_root else relative
                    info = zipfile.ZipInfo.from_file(path, arcname.as_posix())
                    info.date_time = (2020, 1, 1, 0, 0, 0)
                    info.external_attr = 0o100644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with path.open("rb") as raw, archive.open(info, "w", force_zip64=True) as packed:
                        shutil.copyfileobj(raw, packed, length=1024 * 1024)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _record(kind: str, resource_id: str, display_name: str, source: Path, output: Path) -> ResourceRecord:
        digest = hashlib.sha256()
        with output.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return ResourceRecord(kind, resource_id, display_name, output.name, source, output, output.stat().st_size, digest.hexdigest())

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, suffix=".tmp", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)
