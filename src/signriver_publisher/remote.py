from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .gitlink import GitLinkError, GitLinkRepository
from .models import GameProfile


@dataclass(frozen=True, slots=True)
class RemoteAsset:
    asset_id: str
    name: str
    display_size: str
    url: str


@dataclass(frozen=True, slots=True)
class RemoteRelease:
    release_id: str
    tag: str
    name: str
    body: str
    assets: tuple[RemoteAsset, ...]


@dataclass(frozen=True, slots=True)
class RemoteMutationResult:
    action: str
    asset: RemoteAsset
    warnings: tuple[str, ...] = ()


class RemoteResourceManager:
    def __init__(self, client, repository: GitLinkRepository) -> None:
        self.client = client
        self.repository = repository

    def get_release(self, tag: str) -> RemoteRelease | None:
        return parse_release(self.client.list_releases(self.repository), tag)

    def upload_file(self, profile: GameProfile, path: Path) -> RemoteMutationResult:
        path = path.resolve()
        if not path.is_file():
            raise GitLinkError(f"本地发布文件不存在：{path.name}")
        current = self.get_release(profile.release_tag)
        new_id = self.client.upload(path)
        new_asset = RemoteAsset(new_id, path.name, _format_size(path.stat().st_size), "")
        old_same = tuple(asset for asset in current.assets if asset.name.casefold() == path.name.casefold()) if current else ()
        retained = [asset.asset_id for asset in current.assets if asset not in old_same and asset.asset_id] if current else []
        try:
            if current:
                self.client.update_release(
                    self.repository,
                    release_id=current.release_id,
                    tag=current.tag,
                    name=current.name or profile.display_name,
                    body=current.body,
                    attachment_ids=[*retained, new_id],
                )
                action = "替换" if old_same else "添加"
            else:
                self.client.create_release(
                    self.repository,
                    tag=profile.release_tag,
                    name=profile.display_name,
                    body="SignRiver Publisher 远程资源管理",
                    attachment_ids=[new_id],
                )
                action = "创建并添加"
        except Exception:
            try:
                self.client.delete_attachment(new_id)
            except Exception:
                pass
            raise
        warnings = self._cleanup_assets(old_same)
        return RemoteMutationResult(action, new_asset, warnings)

    def delete_asset(self, profile: GameProfile, asset_id: str) -> RemoteMutationResult:
        current = self.get_release(profile.release_tag)
        if current is None:
            raise GitLinkError(f"远程 Release 不存在：{profile.release_tag}")
        target = next((asset for asset in current.assets if asset.asset_id == asset_id), None)
        if target is None:
            raise GitLinkError("远程附件已经不存在，请刷新列表")
        retained = [asset.asset_id for asset in current.assets if asset.asset_id != asset_id and asset.asset_id]
        self.client.update_release(
            self.repository,
            release_id=current.release_id,
            tag=current.tag,
            name=current.name or profile.display_name,
            body=current.body,
            attachment_ids=retained,
        )
        warnings = self._cleanup_assets((target,))
        return RemoteMutationResult("删除", target, warnings)

    def _cleanup_assets(self, assets: tuple[RemoteAsset, ...]) -> tuple[str, ...]:
        warnings: list[str] = []
        for asset in assets:
            try:
                self.client.delete_attachment(asset.asset_id)
            except GitLinkError as error:
                warnings.append(f"附件已从 Release 移除，但清理存储失败：{asset.name}（{error}）")
        return tuple(warnings)


def parse_release(payload: dict[str, object], tag: str) -> RemoteRelease | None:
    candidates: list[object] = []
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("releases"), list):
        candidates = data["releases"]
    elif isinstance(payload.get("releases"), list):
        candidates = payload["releases"]
    for item in candidates:
        if not isinstance(item, dict) or str(item.get("tag_name", "")) != tag:
            continue
        release_id = item.get("id") or item.get("version_id") or item.get("version_gid")
        if release_id is None:
            raise GitLinkError(f"Release {tag} 缺少 ID")
        assets: list[RemoteAsset] = []
        raw_assets = item.get("attachments", [])
        if isinstance(raw_assets, list):
            for raw in raw_assets:
                if not isinstance(raw, dict):
                    continue
                asset_id = str(raw.get("id", "")).strip()
                name = str(raw.get("title") or raw.get("name") or "").strip()
                if not asset_id or not name:
                    continue
                assets.append(RemoteAsset(asset_id, name, str(raw.get("filesize", "")).strip(), str(raw.get("url", "")).strip()))
        return RemoteRelease(
            release_id=str(release_id),
            tag=tag,
            name=str(item.get("name", "")).strip(),
            body=str(item.get("body", "")).strip(),
            assets=tuple(assets),
        )
    return None


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KiB"
    return f"{size / 1024**2:.1f} MiB"
