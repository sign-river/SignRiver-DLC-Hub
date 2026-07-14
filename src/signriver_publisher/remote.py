from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .gitlink import GitLinkError, GitLinkRepository
from .models import GameProfile, PublishAsset


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


@dataclass(frozen=True, slots=True)
class ReleaseSyncResult:
    action: str
    uploaded: int
    reused: int
    removed: int
    warnings: tuple[str, ...]
    state: dict[str, object]


class RemoteResourceManager:
    def __init__(self, client, repository: GitLinkRepository) -> None:
        self.client = client
        self.repository = repository

    def get_release(self, tag: str) -> RemoteRelease | None:
        return parse_release(self.client.list_releases(self.repository), tag)

    def sync_release(
        self,
        profile: GameProfile,
        assets: tuple[PublishAsset, ...],
        previous_state: dict[str, object],
        *,
        force_upload: frozenset[str] = frozenset(),
        progress: Callable[[int, int, str, str], None] | None = None,
    ) -> ReleaseSyncResult:
        names = [asset.name.casefold() for asset in assets]
        if len(names) != len(set(names)):
            raise GitLinkError("本地发布文件包含重名资源")
        current = self.get_release(profile.release_tag)
        remote_by_id = {asset.asset_id: asset for asset in current.assets if asset.asset_id} if current else {}
        remote_by_name = {asset.name.casefold(): asset for asset in current.assets if asset.name} if current else {}
        raw_previous = previous_state.get("assets") if isinstance(previous_state.get("assets"), dict) else {}
        forced = {name.casefold() for name in force_upload}
        final_ids: list[str] = []
        next_assets: dict[str, object] = {}
        newly_uploaded: list[str] = []
        uploaded = 0
        reused = 0
        recovered_ids: set[str] = set()
        checker = getattr(self.client, "attachment_matches", None)
        recovery_candidates: list[tuple[str, str]] = []
        if checker and isinstance(raw_previous, dict):
            for asset in assets:
                previous = raw_previous.get(asset.name)
                previous_id = str(previous.get("attachment_id", "")) if isinstance(previous, dict) else ""
                if (
                    asset.name.casefold() not in forced
                    and previous_id
                    and previous_id not in remote_by_id
                    and asset.name.casefold() not in remote_by_name
                    and _publish_state_matches(previous, asset)
                ):
                    recovery_candidates.append((previous_id, asset.name))
        if recovery_candidates:
            with ThreadPoolExecutor(max_workers=min(8, len(recovery_candidates))) as pool:
                matches = pool.map(lambda item: (item[0], checker(item[0], item[1])), recovery_candidates)
                recovered_ids = {attachment_id for attachment_id, matches_name in matches if matches_name}
        try:
            for index, asset in enumerate(assets, start=1):
                previous = raw_previous.get(asset.name) if isinstance(raw_previous, dict) else None
                previous_id = str(previous.get("attachment_id", "")) if isinstance(previous, dict) else ""
                remote = remote_by_id.get(previous_id)
                remote_with_same_name = remote_by_name.get(asset.name.casefold())
                state_attachment_matches = previous_id in recovered_ids
                can_reuse = (
                    asset.name.casefold() not in forced
                    and _publish_state_matches(previous, asset)
                    and (
                        (remote is not None and remote.name.casefold() == asset.name.casefold())
                        or remote_with_same_name is not None
                        or state_attachment_matches
                    )
                )
                if can_reuse:
                    # GitLink's upload API returns a UUID, while the Release list
                    # exposes a numeric database ID for the very same attachment.
                    # The Release update accepts the numeric ID, but we retain the
                    # UUID in local state because the attachment endpoint uses it.
                    release_attachment_id = remote_with_same_name.asset_id if remote_with_same_name else previous_id
                    state_attachment_id = previous_id
                    reused += 1
                    stage = "复用"
                    if progress:
                        progress(index, len(assets), asset.name, stage)
                else:
                    stage = "上传"
                    if progress:
                        progress(index, len(assets), asset.name, stage)
                    release_attachment_id = self.client.upload(asset.path)
                    state_attachment_id = release_attachment_id
                    newly_uploaded.append(release_attachment_id)
                    uploaded += 1
                final_ids.append(release_attachment_id)
                next_assets[asset.name] = {
                    "sha256": asset.sha256,
                    "size_bytes": asset.size_bytes,
                    "attachment_id": state_attachment_id,
                }
            body = f"SignRiver Publisher 增量同步 · {len(assets)} 个资源文件"
            if current:
                self.client.update_release(
                    self.repository,
                    release_id=current.release_id,
                    tag=current.tag,
                    name=current.name or profile.display_name,
                    body=body,
                    attachment_ids=final_ids,
                )
                action = "更新"
            else:
                self.client.create_release(
                    self.repository,
                    tag=profile.release_tag,
                    name=profile.display_name,
                    body=body,
                    attachment_ids=final_ids,
                )
                action = "创建"
        except Exception:
            for attachment_id in newly_uploaded:
                try:
                    self.client.delete_attachment(attachment_id)
                except Exception:
                    pass
            raise
        # Only locally recorded upload IDs are safe to send to the attachment
        # endpoint. Release assets use unrelated numeric IDs and are already
        # detached by the Release update above.
        retained_storage_ids = {
            str(value.get("attachment_id", ""))
            for value in next_assets.values()
            if isinstance(value, dict) and value.get("attachment_id")
        }
        obsolete_by_id: dict[str, RemoteAsset] = {}
        if isinstance(raw_previous, dict):
            for name, value in raw_previous.items():
                if not isinstance(value, dict):
                    continue
                attachment_id = str(value.get("attachment_id", ""))
                if attachment_id and attachment_id not in retained_storage_ids and attachment_id not in obsolete_by_id:
                    obsolete_by_id[attachment_id] = RemoteAsset(attachment_id, str(name), "", "")
        obsolete = tuple(obsolete_by_id.values())
        warnings = self._cleanup_assets(obsolete)
        state: dict[str, object] = {
            "version": 1,
            "owner": self.repository.owner,
            "repository": self.repository.name,
            "release_tag": profile.release_tag,
            "assets": next_assets,
        }
        return ReleaseSyncResult(action, uploaded, reused, len(obsolete), warnings, state)

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
            # Release list IDs are numeric database keys, not attachment UUIDs.
            # Removing them from attachment storage with the numeric key always
            # returns GitLink's application-level 404.
            if asset.asset_id.isdigit():
                continue
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
        release_id = item.get("version_id") or item.get("id") or item.get("version_gid")
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


def _publish_state_matches(value: object, asset: PublishAsset) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        return value.get("sha256") == asset.sha256 and int(value.get("size_bytes", -1)) == asset.size_bytes
    except (TypeError, ValueError):
        return False
