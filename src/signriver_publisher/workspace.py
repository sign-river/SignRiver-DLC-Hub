from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path, PurePosixPath

from .cream import SteamAppInfo
from .cartridges import create_builtin_cartridges
from .dlc_naming import (
    AUTO_PREFIX,
    CHILDREN_IF_ROOT,
    VALID_DLC_IMPORT_LAYOUT_MODES,
    VALID_DLC_IMPORT_NAMING_MODES,
    auto_managed_folder,
    parse_managed_folder,
)
from .client_cartridges import export_hub_cartridges
from .freshness import (
    DlcFreshnessReport,
    build_resource_freshness,
    load_freshness_report,
    save_freshness_report,
)
from .models import GameProfile, PublishAsset, ResourceRecord
from .steam import SteamApiError, SteamStoreClient

RELEASE_PART_SIZE = 280 * 1024 * 1024
_BUILD_COMPLETE_VERSION = 1
_RELEASE_PART = re.compile(
    r"^(?P<base>dlc\d{3,}_[a-z0-9_-]+\.zip)"
    r"\.part(?P<index>\d{3})-of-(?P<total>\d{3})$",
    re.I,
)

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
        # Full release validation intentionally hashes every attachment once.
        # Repeated UI refreshes can then reuse the verified digest while the
        # file identity (size and both Windows timestamps) remains unchanged.
        self._verified_digest_cache: dict[tuple[str, int, int, int], str] = {}

    def initialize(self) -> GameProfile:
        self.games_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        initial = self.list_games()
        existing = {profile.game_id: profile for profile in initial}
        builtins = create_builtin_cartridges()
        for profile in builtins:
            current_profile = existing.get(profile.game_id)
            if current_profile is None:
                self.save_game(profile)
                continue
            if current_profile.display_name != profile.display_name:
                updated = replace(current_profile, display_name=profile.display_name)
                self.save_game(updated)
                existing[profile.game_id] = updated
        if initial:
            return existing[initial[0].game_id]
        return builtins[0]

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
        self._invalidate_build_complete(profile)

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
        managed_name = source.name
        parsed = parse_managed_folder(source.name)
        if profile.dlc_import_naming_mode == AUTO_PREFIX and parsed is None:
            try:
                managed_name = auto_managed_folder(
                    source.name, self._next_dlc_import_number(profile)
                )
            except ValueError as error:
                raise WorkspaceError(str(error)) from error
        self._parse_dlc_folder(managed_name)
        destination = self.game_dir(profile.game_id) / "dlc" / managed_name
        if destination.exists():
            raise WorkspaceError(f"DLC 已存在：{managed_name}")
        staging_root = self._import_staging_root(profile)
        staging_root.mkdir(parents=True, exist_ok=True)
        staging = staging_root / uuid.uuid4().hex[:8]
        try:
            self._copy_directory(source, staging)
            staging.replace(destination)
        except (OSError, shutil.Error) as error:
            raise self._copy_workspace_error(source.name, error) from error
        finally:
            if staging.exists():
                self._remove_tree(staging)
        self._advance_dlc_import_number(profile, managed_name)
        self._invalidate_build_complete(profile)
        return destination

    def is_dlc_collection(self, profile: GameProfile, source: Path) -> bool:
        source = source.resolve()
        configured_root = PurePosixPath(
            profile.dlc_relative_dir.replace("\\", "/")
        ).name
        return (
            profile.dlc_import_layout_mode == CHILDREN_IF_ROOT
            and source.is_dir()
            and source.name.casefold() == configured_root.casefold()
            and any(path.is_dir() and not path.is_symlink() for path in source.iterdir())
        )

    def import_dlc_collection(
        self, profile: GameProfile, source: Path, *, progress=None
    ) -> tuple[Path, ...]:
        source = source.resolve()
        if not self.is_dlc_collection(profile, source):
            raise WorkspaceError("所选目录不是当前卡带配置的 DLC 根目录")
        children = tuple(
            sorted(
                (
                    path for path in source.iterdir()
                    if path.is_dir() and not path.is_symlink()
                ),
                key=lambda path: path.name.casefold(),
            )
        )
        dlc_root = self.game_dir(profile.game_id) / "dlc"
        existing_install_names = {
            parsed[1].casefold()
            for path in dlc_root.iterdir()
            if path.is_dir()
            for parsed in [parse_managed_folder(path.name)]
            if parsed is not None
        }
        first_number = self._next_dlc_import_number(profile)
        planned: list[tuple[Path, Path]] = []
        for offset, child in enumerate(children):
            if child.name.casefold() in existing_install_names:
                raise WorkspaceError(f"DLC 已存在：{child.name}")
            try:
                managed_name = auto_managed_folder(child.name, first_number + offset)
            except ValueError as error:
                raise WorkspaceError(str(error)) from error
            destination = dlc_root / managed_name
            if destination.exists():
                raise WorkspaceError(f"DLC 已存在：{managed_name}")
            planned.append((child, destination))

        staging_root = self._import_staging_root(profile)
        staging_root.mkdir(parents=True, exist_ok=True)
        batch = staging_root / uuid.uuid4().hex[:8]
        batch.mkdir()
        committed: list[tuple[Path, Path]] = []
        current_name = source.name
        try:
            for index, (child, destination) in enumerate(planned, start=1):
                current_name = child.name
                if progress is not None:
                    progress(index, len(children), child.name)
                self._copy_directory(child, batch / destination.name)
            for _, destination in planned:
                staged = batch / destination.name
                staged.replace(destination)
                committed.append((destination, staged))
        except (OSError, shutil.Error) as error:
            for destination, staged in reversed(committed):
                if destination.exists():
                    destination.replace(staged)
            raise self._copy_workspace_error(current_name, error) from error
        finally:
            if batch.exists():
                self._remove_tree(batch, ignore_errors=True)
        self._atomic_json(
            self.game_dir(profile.game_id) / ".dlc-import-state.json",
            {"version": 1, "next_number": first_number + len(planned)},
        )
        self._invalidate_build_complete(profile)
        return tuple(destination for _, destination in planned)

    def interrupted_collection_import(
        self, profile: GameProfile, source: Path
    ) -> tuple[Path, ...]:
        if not self.is_dlc_collection(profile, source):
            return ()
        staging_roots = self._import_staging_roots(profile)
        if not any(root.is_dir() and any(root.iterdir()) for root in staging_roots):
            return ()
        source_names = {
            path.name.casefold() for path in source.iterdir()
            if path.is_dir() and not path.is_symlink()
        }
        candidates: list[tuple[int, Path]] = []
        for path in (self.game_dir(profile.game_id) / "dlc").iterdir():
            parsed = parse_managed_folder(path.name) if path.is_dir() else None
            if parsed is not None and parsed[1].casefold() in source_names:
                candidates.append((parsed[2], path))
        if not candidates or min(number for number, _ in candidates) <= 1:
            return ()
        return tuple(path for _, path in sorted(candidates))

    def reset_interrupted_collection_import(
        self, profile: GameProfile, source: Path
    ) -> int:
        candidates = self.interrupted_collection_import(profile, source)
        if not candidates:
            raise WorkspaceError("没有找到可安全重置的中断导入记录")
        for path in candidates:
            self._remove_tree(path)
        for staging_root in self._import_staging_roots(profile):
            if staging_root.exists():
                self._remove_tree(staging_root)
        self._atomic_json(
            self.game_dir(profile.game_id) / ".dlc-import-state.json",
            {"version": 1, "next_number": 1},
        )
        self._invalidate_build_complete(profile)
        return len(candidates)

    def wrapped_collection_import(
        self, profile: GameProfile, source: Path
    ) -> Path | None:
        if not self.is_dlc_collection(profile, source):
            return None
        expected_children = {
            path.name.casefold() for path in source.iterdir()
            if path.is_dir() and not path.is_symlink()
        }
        for candidate in (self.game_dir(profile.game_id) / "dlc").iterdir():
            parsed = parse_managed_folder(candidate.name) if candidate.is_dir() else None
            if parsed is None or parsed[1].casefold() != source.name.casefold():
                continue
            actual_children = {
                path.name.casefold() for path in candidate.iterdir()
                if path.is_dir() and not path.is_symlink()
            }
            if expected_children and expected_children == actual_children:
                return candidate
        return None

    def discard_wrapped_collection_import(
        self, profile: GameProfile, source: Path
    ) -> None:
        candidate = self.wrapped_collection_import(profile, source)
        if candidate is None:
            raise WorkspaceError("没有找到可安全清理的整目录误导入记录")
        shutil.rmtree(candidate)
        remaining_numbers = [
            parsed[2]
            for path in (self.game_dir(profile.game_id) / "dlc").iterdir()
            if path.is_dir()
            for parsed in [parse_managed_folder(path.name)]
            if parsed is not None
        ]
        self._atomic_json(
            self.game_dir(profile.game_id) / ".dlc-import-state.json",
            {"version": 1, "next_number": max(remaining_numbers, default=0) + 1},
        )
        self._invalidate_build_complete(profile)

    def split_wrapped_collection_import(
        self, profile: GameProfile, source: Path, *, progress=None
    ) -> tuple[Path, ...]:
        candidate = self.wrapped_collection_import(profile, source)
        if candidate is None:
            raise WorkspaceError("没有找到可安全拆分的整目录误导入记录")
        direct_files = tuple(path for path in candidate.iterdir() if not path.is_dir())
        if direct_files:
            raise WorkspaceError("整目录中包含直属文件，无法自动拆分，请先人工确认")
        children = tuple(
            sorted(
                (path for path in candidate.iterdir() if path.is_dir()),
                key=lambda path: path.name.casefold(),
            )
        )
        dlc_root = self.game_dir(profile.game_id) / "dlc"
        remaining_numbers = [
            parsed[2]
            for path in dlc_root.iterdir()
            if path.is_dir() and path != candidate
            for parsed in [parse_managed_folder(path.name)]
            if parsed is not None
        ]
        first_number = max(remaining_numbers, default=0) + 1
        planned: list[tuple[Path, Path]] = []
        for offset, child in enumerate(children):
            try:
                managed_name = auto_managed_folder(child.name, first_number + offset)
            except ValueError as error:
                raise WorkspaceError(str(error)) from error
            destination = dlc_root / managed_name
            if destination.exists() and destination != candidate:
                raise WorkspaceError(f"DLC 已存在：{managed_name}")
            planned.append((child, destination))

        staging_root = self._import_staging_root(profile)
        staging_root.mkdir(parents=True, exist_ok=True)
        staged_wrapper = staging_root / f"w-{uuid.uuid4().hex[:8]}"
        candidate.replace(staged_wrapper)
        moved: list[tuple[Path, Path]] = []
        try:
            for index, (old_child, destination) in enumerate(planned, start=1):
                staged_child = staged_wrapper / old_child.name
                if progress is not None:
                    progress(index, len(planned), old_child.name)
                staged_child.replace(destination)
                moved.append((destination, staged_child))
            staged_wrapper.rmdir()
        except Exception:
            for destination, staged_child in reversed(moved):
                if destination.exists():
                    destination.replace(staged_child)
            if staged_wrapper.exists() and not candidate.exists():
                staged_wrapper.replace(candidate)
            raise
        next_number = first_number + len(planned)
        self._atomic_json(
            self.game_dir(profile.game_id) / ".dlc-import-state.json",
            {"version": 1, "next_number": next_number},
        )
        self._invalidate_build_complete(profile)
        return tuple(destination for _, destination in planned)

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
        self._invalidate_build_complete(profile)
        return destination

    def remove_source(self, profile: GameProfile, kind: str, name: str) -> None:
        if kind not in {"dlc", "patches"}:
            raise WorkspaceError("未知资源类型")
        root = (self.game_dir(profile.game_id) / kind).resolve()
        target = (root / name).resolve()
        if target.parent != root or not target.exists():
            raise WorkspaceError("资源不存在或路径不安全")
        if target.is_dir():
            self._remove_tree(target)
        else:
            target.unlink()
        self._invalidate_build_complete(profile)

    def clear_sources(self, profile: GameProfile, kind: str) -> int:
        if kind not in {"dlc", "patches"}:
            raise WorkspaceError("未知资源类型")
        root = (self.game_dir(profile.game_id) / kind).resolve()
        resources = tuple(root.iterdir())
        for target in resources:
            resolved = target.resolve()
            if resolved.parent != root:
                raise WorkspaceError(f"资源路径不安全：{target.name}")
            if target.is_dir():
                self._remove_tree(target)
            else:
                target.unlink()
        if kind == "dlc":
            for staging in self._import_staging_roots(profile):
                if staging.exists():
                    self._remove_tree(staging)
            for state_name in (".dlc-import-state.json", ".build-state.json"):
                (self.game_dir(profile.game_id) / state_name).unlink(missing_ok=True)
        self._invalidate_build_complete(profile)
        return len(resources)

    @staticmethod
    def compression_worker_count() -> int:
        """Use roughly one worker per physical core, capped to protect disks."""
        logical_cpus = os.cpu_count() or 2
        return max(1, min(8, logical_cpus // 2 or 1))

    def build(self, profile: GameProfile, *, progress=None) -> tuple[ResourceRecord, ...]:
        self._validate_profile(profile)
        # A previous output must never remain publishable while a new build is
        # incomplete.  The completion manifest is recreated only after every
        # DLC, patch, AppInfo file, and stale-output cleanup has succeeded.
        self._invalidate_build_complete(profile)
        dlcs, patches = self.scan_sources(profile)
        target = self.output_dir / profile.game_id
        target.mkdir(parents=True, exist_ok=True)
        records: list[ResourceRecord] = []
        expected: set[str] = set()
        build_state = self._load_build_state(profile)
        previous_dlcs = build_state.get("dlcs") if isinstance(build_state.get("dlcs"), dict) else {}
        next_dlcs: dict[str, object] = {}

        total_dlcs = len(dlcs)
        plans: list[dict[str, object]] = []
        compression_jobs: list[dict[str, object]] = []

        def report(stage: str, index: int, name: str, detail: str = "") -> None:
            if progress is not None:
                progress(stage, index, total_dlcs, name, detail)

        for index, source in enumerate(dlcs, start=1):
            report("正在检查", index, source.name)
            dlc_id, display_name = self._parse_dlc_folder(source.name)
            asset_name = f"{source.name}.zip"
            output = target / asset_name
            archive_root = self._dlc_archive_root(profile, source)
            source_signature = hashlib.sha256(
                (archive_root + "\0" + self._source_signature(source)).encode("utf-8")
            ).hexdigest()
            cached = previous_dlcs.get(source.name) if isinstance(previous_dlcs, dict) else None
            cached_parts = self._cached_release_parts(
                cached, source_signature, asset_name, target
            )
            reusable = self._cached_output_matches(cached, source_signature, asset_name, output)
            plan: dict[str, object] = {
                "index": index,
                "source": source,
                "dlc_id": dlc_id,
                "display_name": display_name,
                "asset_name": asset_name,
                "output": output,
                "archive_root": archive_root,
                "source_signature": source_signature,
                "cached": cached,
            }
            if cached_parts:
                plan["digest"] = str(cached["sha256"])
                plan["parts"] = cached_parts
                plan["full_size"] = int(cached["size_bytes"])
                report(
                    "复用已有分卷", index, source.name,
                    f"{len(cached_parts)} 卷 · 无需保留完整 ZIP",
                )
            elif reusable:
                plan["digest"] = str(cached["sha256"])
                report(
                    "复用已有压缩包", index, source.name,
                    f"{output.stat().st_size / 1024 / 1024:.1f} MiB",
                )
            elif cached is None and self._existing_zip_matches_source(
                source, output, archive_root=archive_root
            ):
                # Adopt ZIPs produced by older publisher versions into the new
                # incremental state without recompressing every DLC once.
                plan["digest"] = self._file_sha256(output)
                report(
                    "接管已有压缩包", index, source.name,
                    f"{output.stat().st_size / 1024 / 1024:.1f} MiB",
                )
            else:
                compression_jobs.append(plan)
            plans.append(plan)

        def compress(plan: dict[str, object]) -> str:
            source = Path(plan["source"])
            output = Path(plan["output"])
            index = int(plan["index"])
            archive_root = str(plan["archive_root"])
            report("开始压缩", index, source.name)
            started = time.monotonic()
            self._zip_directory(
                source, output, include_root=True, archive_root=archive_root
            )
            digest = self._file_sha256(output)
            elapsed = time.monotonic() - started
            report(
                "压缩完成", index, source.name,
                f"{output.stat().st_size / 1024 / 1024:.1f} MiB · {elapsed:.1f} 秒",
            )
            return digest

        if compression_jobs:
            worker_count = min(self.compression_worker_count(), len(compression_jobs))
            if progress is not None:
                progress(
                    "并行压缩准备", 0, total_dlcs, "",
                    f"{len(compression_jobs)} 个待处理资源 · {worker_count} 个并行任务",
                )
            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="dlc-zip",
            ) as executor:
                futures = {
                    executor.submit(compress, plan): plan
                    for plan in compression_jobs
                }
                try:
                    for future in as_completed(futures):
                        futures[future]["digest"] = future.result()
                except Exception:
                    for future in futures:
                        future.cancel()
                    raise

        for plan in plans:
            source = Path(plan["source"])
            output = Path(plan["output"])
            asset_name = str(plan["asset_name"])
            digest = str(plan["digest"])
            cached = plan.get("cached")
            cached_part_records = plan.get("parts")
            if isinstance(cached_part_records, tuple):
                part_records = cached_part_records
                full_size = int(plan["full_size"])
                full_mtime_ns = 0
            else:
                output_stat = output.stat()
                full_size = output_stat.st_size
                full_mtime_ns = output_stat.st_mtime_ns
                if output_stat.st_size > RELEASE_PART_SIZE:
                    report("正在生成分卷", int(plan["index"]), source.name, "每卷最大 280 MiB")
                part_records = self._ensure_release_parts(output, RELEASE_PART_SIZE)
            if part_records:
                report("分卷完成", int(plan["index"]), source.name, f"共 {len(part_records)} 卷")
            cached_part_metadata = {
                str(value.get("asset_name")): value
                for value in (cached.get("parts", []) if isinstance(cached, dict) else [])
                if isinstance(value, dict)
            }
            part_metadata = []
            for part in part_records:
                stat = part.stat()
                previous_part = cached_part_metadata.get(part.name)
                part_metadata.append({
                    "asset_name": part.name,
                    "size_bytes": stat.st_size,
                    "output_mtime_ns": stat.st_mtime_ns,
                    "sha256": self._cached_publish_digest(
                        previous_part, stat.st_size, stat.st_mtime_ns
                    ) or self._file_sha256(part),
                })
            next_dlcs[source.name] = {
                "source_signature": str(plan["source_signature"]),
                "asset_name": asset_name,
                "size_bytes": full_size,
                "output_mtime_ns": full_mtime_ns,
                "sha256": digest,
                "parts": part_metadata,
            }
            if part_records:
                records.append(ResourceRecord(
                    "dlc", str(plan["dlc_id"]), str(plan["display_name"]),
                    asset_name, source, part_records[0], full_size, digest,
                ))
                output.unlink(missing_ok=True)
            else:
                records.append(self._record(
                    "dlc", str(plan["dlc_id"]), str(plan["display_name"]),
                    source, output, digest=digest,
                ))
                expected.add(asset_name)
            expected.update(part.name for part in part_records)

        # Persist completed ZIP work before contacting Steam so a transient API
        # failure does not force every unchanged DLC to be compressed again.
        self._atomic_json(self._build_state_path(profile), {"version": 1, "dlcs": next_dlcs})

        patch_by_name = {path.name.lower(): path for path in patches}
        for dll_name in profile.patch_asset_names:
            source = patch_by_name.get(dll_name)
            if source is None or not source.is_file():
                raise WorkspaceError(f"补丁目录缺少 {dll_name}")

        if progress is not None:
            progress("正在刷新", 0, total_dlcs, profile.appinfo_name, "Steam AppInfo")
        appinfo = self.refresh_appinfo(profile)
        appinfo_output = target / profile.appinfo_name
        records.append(self._record("appinfo", appinfo.app_id, appinfo.name, appinfo_output, appinfo_output))
        expected.add(profile.appinfo_name)

        for source in patches:
            if source.name.lower() in {profile.appinfo_name.lower(), "cream_api.ini"}:
                continue
            if progress is not None:
                progress("正在整理补丁", 0, total_dlcs, source.name, "")
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

        self._write_build_complete(profile)
        return tuple(records)

    def refresh_appinfo(self, profile: GameProfile) -> SteamAppInfo:
        self._validate_profile(profile)
        # A standalone Steam refresh changes one release attachment without
        # rebuilding the rest.  Invalidating is safer than silently blessing a
        # mixture of outputs from different build generations.
        self._invalidate_build_complete(profile)
        if not profile.steam_app_id:
            raise WorkspaceError("当前游戏没有配置 Steam App ID")
        target = self.output_dir / profile.game_id / profile.appinfo_name
        # A failed refresh must not leave an older AppInfo publishable as if it
        # belonged to the current build.
        target.unlink(missing_ok=True)
        legacy_cache = self.game_dir(profile.game_id) / ".cache" / profile.appinfo_name
        legacy_cache.unlink(missing_ok=True)
        try:
            appinfo = self._appinfo_provider(profile.steam_app_id)
        except SteamApiError as error:
            raise WorkspaceError(str(error)) from error
        if appinfo.app_id != profile.steam_app_id:
            raise WorkspaceError(f"Steam 返回的 App ID 是 {appinfo.app_id}，当前游戏要求 {profile.steam_app_id}")
        payload = self._appinfo_payload(appinfo)
        self._atomic_json(target, payload)
        return appinfo

    def freshness_path(self, profile: GameProfile) -> Path:
        return self.game_dir(profile.game_id) / "freshness.json"

    def load_freshness(self, profile: GameProfile) -> DlcFreshnessReport | None:
        path = self.freshness_path(profile)
        try:
            return load_freshness_report(path)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return None

    def detect_dlc_freshness(self, profile: GameProfile) -> DlcFreshnessReport:
        """Refresh the local resource timestamp stamp (no Steam comparison)."""
        return self.refresh_resource_freshness(profile)

    def refresh_resource_freshness(self, profile: GameProfile) -> DlcFreshnessReport:
        """Record the newest local package / publish-output modification time."""
        dlcs, _patches = self.scan_sources(profile)
        published_paths = self._published_dlc_paths(profile)
        report = build_resource_freshness(
            local_folders=dlcs,
            published_paths=published_paths,
            published_package_count=len(published_paths),
        )
        save_freshness_report(self.freshness_path(profile), report)
        return report

    def _published_dlc_paths(self, profile: GameProfile) -> tuple[Path, ...]:
        target = self.output_dir / profile.game_id
        if not target.is_dir():
            return ()
        paths: list[Path] = []
        for path in target.iterdir():
            if not path.is_file():
                continue
            name = path.name
            stem = path.stem
            if path.suffix.casefold() == ".zip" and _DLC_DIR.fullmatch(stem):
                paths.append(path)
                continue
            if _RELEASE_PART.fullmatch(name):
                paths.append(path)
        return tuple(sorted(paths, key=lambda item: item.name.casefold()))

    def _published_dlc_package_count(self, profile: GameProfile) -> int:
        return len(self._published_dlc_paths(profile))

    def publish_files(self, profile: GameProfile) -> tuple[Path, ...]:
        return tuple(asset.path for asset in self._validated_publish_assets(profile))

    def publish_assets(self, profile: GameProfile) -> tuple[PublishAsset, ...]:
        return self._validated_publish_assets(profile)

    def export_client_hub(self, *, default_game_id: str | None = None) -> tuple[Path, ...]:
        """Materialise client cartridge documents and the hub index for upload."""
        profiles = self.list_games()
        if not profiles:
            raise WorkspaceError("没有可导出的游戏卡带")
        announcement = self.root / "announcement.json"
        freshness = {
            profile.game_id: self.refresh_resource_freshness(profile).to_client_dict()
            for profile in profiles
        }
        return export_hub_cartridges(
            profiles,
            self.output_dir / "hub",
            default_game_id=default_game_id or profiles[0].game_id,
            announcement_path=announcement if announcement.is_file() else None,
            freshness_by_game=freshness,
        )

    def _unvalidated_publish_files(self, profile: GameProfile) -> tuple[Path, ...]:
        target = self.output_dir / profile.game_id
        appinfo = target / profile.appinfo_name
        if not appinfo.is_file():
            raise WorkspaceError("请先生成发布包")
        for name in profile.patch_asset_names:
            if not (target / name).is_file():
                raise WorkspaceError(f"发布包缺少 {name}，请先生成全部发布文件")
        files = tuple(sorted(path for path in target.iterdir() if path.is_file()))
        split_bases = {
            match.group("base").casefold()
            for path in files
            if (match := _RELEASE_PART.fullmatch(path.name)) is not None
        }
        return tuple(
            path for path in files
            if not (path.name.casefold() in split_bases and path.suffix.casefold() == ".zip")
        )

    def _snapshot_publish_assets(
        self, profile: GameProfile, files: tuple[Path, ...]
    ) -> tuple[PublishAsset, ...]:
        build_state = self._load_build_state(profile)
        raw_dlcs = build_state.get("dlcs") if isinstance(build_state.get("dlcs"), dict) else {}
        cached_by_asset: dict[str, dict[str, object]] = {}
        if isinstance(raw_dlcs, dict):
            for value in raw_dlcs.values():
                if isinstance(value, dict) and isinstance(value.get("asset_name"), str):
                    cached_by_asset[str(value["asset_name"])] = value
                    raw_parts = value.get("parts")
                    if isinstance(raw_parts, list):
                        for part in raw_parts:
                            if isinstance(part, dict) and isinstance(part.get("asset_name"), str):
                                cached_by_asset[str(part["asset_name"])] = part
        assets: list[PublishAsset] = []
        for path in files:
            stat = path.stat()
            cached = cached_by_asset.get(path.name)
            digest = self._cached_publish_digest(cached, stat.st_size, stat.st_mtime_ns) or self._file_sha256(path)
            assets.append(PublishAsset(path, path.name, stat.st_size, digest))
        return tuple(assets)

    def _write_build_complete(self, profile: GameProfile) -> None:
        files = self._unvalidated_publish_files(profile)
        assets = self._snapshot_publish_assets(profile, files)
        oversized = next(
            (asset for asset in assets if asset.size_bytes > RELEASE_PART_SIZE), None
        )
        if oversized is not None:
            raise WorkspaceError(
                f"发布附件超过安全上限 280 MiB：{oversized.name}"
            )
        self._validate_release_parts(tuple(asset.name for asset in assets))
        payload = {
            "version": _BUILD_COMPLETE_VERSION,
            "profile": profile.to_dict(),
            "assets": [
                {
                    "name": asset.name,
                    "size_bytes": asset.size_bytes,
                    "sha256": asset.sha256,
                }
                for asset in assets
            ],
        }
        self._atomic_json(self._build_complete_path(profile), payload)
        self.refresh_resource_freshness(profile)

    def _validated_publish_assets(
        self, profile: GameProfile
    ) -> tuple[PublishAsset, ...]:
        self._validate_profile(profile)
        files = self._unvalidated_publish_files(profile)
        manifest_path = self._build_complete_path(profile)
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise WorkspaceError(
                "发布文件没有完整构建凭证，请重新生成全部发布文件"
            ) from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("version") != _BUILD_COMPLETE_VERSION
            or manifest.get("profile") != profile.to_dict()
            or not isinstance(manifest.get("assets"), list)
        ):
            raise WorkspaceError("构建凭证与当前游戏卡带不一致，请重新构建")

        recorded: dict[str, dict[str, object]] = {}
        recorded_casefold: set[str] = set()
        for value in manifest["assets"]:
            if not isinstance(value, dict):
                raise WorkspaceError("构建凭证中的附件记录无效，请重新构建")
            name = str(value.get("name", ""))
            folded = name.casefold()
            if (
                not name
                or Path(name).name != name
                or folded in recorded_casefold
            ):
                raise WorkspaceError("构建凭证中的附件名称无效或重复，请重新构建")
            recorded[name] = value
            recorded_casefold.add(folded)

        target = self.output_dir / profile.game_id
        actual_all = tuple(sorted(path for path in target.iterdir() if path.is_file()))
        actual_names = {path.name for path in actual_all}
        if actual_names != set(recorded):
            raise WorkspaceError("发布文件与完整构建凭证不一致，请重新构建")
        if {path.name for path in files} != actual_names:
            raise WorkspaceError("发布目录包含不应上传的完整压缩包，请重新构建")

        self._validate_release_parts(tuple(recorded))
        assets: list[PublishAsset] = []
        for path in files:
            value = recorded[path.name]
            try:
                expected_size = int(value.get("size_bytes", -1))
                expected_sha256 = str(value.get("sha256", ""))
                stat = path.stat()
            except (OSError, TypeError, ValueError) as error:
                raise WorkspaceError(
                    f"无法验证发布文件：{path.name}"
                ) from error
            if stat.st_size > RELEASE_PART_SIZE:
                raise WorkspaceError(
                    f"发布附件超过安全上限 280 MiB：{path.name}"
                )
            if expected_size != stat.st_size or len(expected_sha256) != 64:
                raise WorkspaceError(f"发布文件已变化，请重新构建：{path.name}")
            digest = self._verified_file_sha256(path)
            if digest != expected_sha256:
                raise WorkspaceError(f"发布文件校验失败，请重新构建：{path.name}")
            assets.append(PublishAsset(path, path.name, stat.st_size, digest))
        return tuple(assets)

    @staticmethod
    def _validate_release_parts(names: tuple[str, ...]) -> None:
        groups: dict[str, list[tuple[int, int]]] = {}
        folded_names = {name.casefold() for name in names}
        for name in names:
            match = _RELEASE_PART.fullmatch(name)
            if match is None:
                continue
            base = match.group("base").casefold()
            groups.setdefault(base, []).append(
                (int(match.group("index")), int(match.group("total")))
            )
        for base, parts in groups.items():
            totals = {total for _, total in parts}
            if (
                len(totals) != 1
                or next(iter(totals)) < 2
                or base in folded_names
            ):
                raise WorkspaceError(f"DLC 分卷记录无效：{base}")
            total = next(iter(totals))
            if len(parts) != total or {index for index, _ in parts} != set(
                range(1, total + 1)
            ):
                raise WorkspaceError(f"DLC 分卷不完整：{base}")

    def load_publish_state(self, profile: GameProfile, owner: str, repository: str) -> dict[str, object]:
        path = self._publish_state_path(profile)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict) or value.get("version") != 1:
            return {}
        if value.get("owner") != owner or value.get("repository") != repository or value.get("release_tag") != profile.release_tag:
            return {}
        return value

    def save_publish_state(self, profile: GameProfile, state: dict[str, object]) -> None:
        self._atomic_json(self._publish_state_path(profile), state)

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
        patch_names = profile.patch_asset_names
        if len({name.casefold() for name in patch_names}) != len(patch_names):
            raise WorkspaceError("补丁 DLL 文件名不能重复")
        for name in patch_names:
            if not name or Path(name).name != name or name in {".", ".."}:
                raise WorkspaceError("补丁 DLL 必须使用普通文件名")
        PublisherWorkspace._validate_relative_directory(
            profile.dlc_relative_dir, "DLC 安装目录"
        )
        PublisherWorkspace._validate_relative_directory(
            profile.patch_relative_dir, "补丁安装目录"
        )
        if profile.dlc_archive_root_mode not in {"source", "strip_id_prefix"}:
            raise WorkspaceError("DLC 压缩根目录模式只能是 source 或 strip_id_prefix")
        if profile.dlc_import_naming_mode not in VALID_DLC_IMPORT_NAMING_MODES:
            raise WorkspaceError(
                "DLC 导入命名模式只能是 manual_prefixed 或 auto_prefix"
            )
        if profile.dlc_import_layout_mode not in VALID_DLC_IMPORT_LAYOUT_MODES:
            raise WorkspaceError(
                "DLC 导入布局模式只能是 single_directory 或 children_if_root"
            )

    def _next_dlc_import_number(self, profile: GameProfile) -> int:
        state_path = self.game_dir(profile.game_id) / ".dlc-import-state.json"
        stored = 1
        try:
            value = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                stored = max(1, int(value.get("next_number", 1)))
        except (OSError, ValueError, TypeError):
            pass
        existing = 0
        dlc_dir = self.game_dir(profile.game_id) / "dlc"
        for path in dlc_dir.iterdir():
            parsed = parse_managed_folder(path.name) if path.is_dir() else None
            if parsed is not None:
                existing = max(existing, parsed[2])
        return max(stored, existing + 1)

    def _advance_dlc_import_number(self, profile: GameProfile, managed_name: str) -> None:
        parsed = parse_managed_folder(managed_name)
        if parsed is None:
            return
        path = self.game_dir(profile.game_id) / ".dlc-import-state.json"
        next_number = max(self._next_dlc_import_number(profile), parsed[2] + 1)
        self._atomic_json(path, {"version": 1, "next_number": next_number})

    def _import_staging_root(self, profile: GameProfile) -> Path:
        return self.root / ".staging" / profile.game_id

    def _import_staging_roots(self, profile: GameProfile) -> tuple[Path, ...]:
        # The second path is retained only to detect and clean residues created
        # by publisher builds before the short Windows-safe staging layout.
        return (
            self._import_staging_root(profile),
            self.game_dir(profile.game_id) / ".import-staging",
        )

    @staticmethod
    def _copy_file_with_retry(source: str, destination: str) -> str:
        last_error: OSError | None = None
        for delay in (0.0, 0.2, 0.6, 1.2):
            if delay:
                time.sleep(delay)
            try:
                return shutil.copy2(source, destination)
            except OSError as error:
                last_error = error
        assert last_error is not None
        raise last_error

    @classmethod
    def _copy_directory(cls, source: Path, destination: Path) -> None:
        shutil.copytree(source, destination, copy_function=cls._copy_file_with_retry)

    @staticmethod
    def _copy_workspace_error(name: str, error: BaseException) -> WorkspaceError:
        if isinstance(error, shutil.Error) and error.args and error.args[0]:
            first = error.args[0][0]
            detail = str(first[2] if isinstance(first, tuple) and len(first) >= 3 else first)
        else:
            detail = str(error)
        return WorkspaceError(f"复制 DLC“{name}”失败：{detail}")

    @staticmethod
    def _remove_tree(path: Path, *, ignore_errors: bool = False) -> None:
        last_error: OSError | None = None
        for delay in (0.0, 0.2, 0.6, 1.2):
            if delay:
                time.sleep(delay)
            try:
                shutil.rmtree(path)
                return
            except FileNotFoundError:
                return
            except OSError as error:
                last_error = error
                continue
        if last_error is not None and not ignore_errors:
            raise last_error

    @staticmethod
    def _dlc_archive_root(profile: GameProfile, source: Path) -> str:
        if profile.dlc_archive_root_mode == "source":
            return source.name
        match = _DLC_DIR.fullmatch(source.name)
        if match is None:
            raise WorkspaceError("无法从 DLC 文件夹名称提取真实安装目录")
        return match.group(2)

    @staticmethod
    def _validate_relative_directory(value: str, label: str) -> None:
        raw = str(value).strip().replace("\\", "/")
        if raw in {"", "."}:
            return
        path = PurePosixPath(raw)
        if (
            path.is_absolute()
            or ".." in path.parts
            or "\x00" in raw
            or any(":" in part or part in {"", "."} for part in path.parts)
        ):
            raise WorkspaceError(f"{label}必须是游戏根目录内的安全相对路径")

    @staticmethod
    def _parse_dlc_folder(name: str) -> tuple[str, str]:
        match = _DLC_DIR.fullmatch(name)
        if not match:
            raise WorkspaceError("DLC 文件夹应命名为 dlc001_英文名称")
        display = match.group(2).replace("_", " ").strip().title()
        return match.group(1).lower(), display

    @staticmethod
    def _zip_directory(
        source: Path, destination: Path, *, include_root: bool,
        archive_root: str | None = None,
    ) -> None:
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
                    root_name = archive_root or source.name
                    arcname = Path(root_name) / relative if include_root else relative
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
    def _ensure_release_parts(archive: Path, part_size: int) -> tuple[Path, ...]:
        """Split a large ZIP without changing its bytes; the client joins it back."""
        pattern = f"{archive.name}.part*-of-*"
        existing = tuple(sorted(archive.parent.glob(pattern)))
        if archive.stat().st_size <= part_size:
            for part in existing:
                part.unlink(missing_ok=True)
            return ()
        count = (archive.stat().st_size + part_size - 1) // part_size
        expected = tuple(
            archive.with_name(f"{archive.name}.part{index:03d}-of-{count:03d}")
            for index in range(1, count + 1)
        )
        if existing == expected and all(
            part.stat().st_size == (
                part_size if index < count else archive.stat().st_size - part_size * (count - 1)
            )
            and part.stat().st_mtime_ns >= archive.stat().st_mtime_ns
            for index, part in enumerate(expected, start=1)
        ):
            return expected
        for part in existing:
            part.unlink(missing_ok=True)
        created: list[Path] = []
        try:
            with archive.open("rb") as source:
                for index, destination in enumerate(expected, start=1):
                    temporary = destination.with_suffix(destination.suffix + ".tmp")
                    with temporary.open("wb") as output:
                        remaining = part_size
                        while remaining:
                            block = source.read(min(1024 * 1024, remaining))
                            if not block:
                                break
                            output.write(block)
                            remaining -= len(block)
                        output.flush()
                        os.fsync(output.fileno())
                    temporary.replace(destination)
                    created.append(destination)
            return tuple(created)
        except Exception:
            for part in created:
                part.unlink(missing_ok=True)
            raise

    @staticmethod
    def _record(kind: str, resource_id: str, display_name: str, source: Path, output: Path, *, digest: str | None = None) -> ResourceRecord:
        digest = digest or PublisherWorkspace._file_sha256(output)
        return ResourceRecord(kind, resource_id, display_name, output.name, source, output, output.stat().st_size, digest)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _verified_file_sha256(self, path: Path) -> str:
        before = path.stat()
        key = (
            str(path.resolve()).casefold(),
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        cached = self._verified_digest_cache.get(key)
        if cached is not None:
            return cached
        digest = self._file_sha256(path)
        after = path.stat()
        if (
            after.st_size != before.st_size
            or after.st_mtime_ns != before.st_mtime_ns
            or after.st_ctime_ns != before.st_ctime_ns
        ):
            raise WorkspaceError(f"发布文件在校验期间发生变化：{path.name}")
        self._verified_digest_cache[key] = digest
        return digest

    def _build_state_path(self, profile: GameProfile) -> Path:
        return self.game_dir(profile.game_id) / ".build-state.json"

    def _build_complete_path(self, profile: GameProfile) -> Path:
        return self.game_dir(profile.game_id) / ".build-complete.json"

    def _invalidate_build_complete(self, profile: GameProfile) -> None:
        self._build_complete_path(profile).unlink(missing_ok=True)
        self._verified_digest_cache.clear()

    def _publish_state_path(self, profile: GameProfile) -> Path:
        return self.game_dir(profile.game_id) / ".publish-state.json"

    @staticmethod
    def _cached_publish_digest(cached: object, size_bytes: int, mtime_ns: int) -> str:
        if not isinstance(cached, dict):
            return ""
        try:
            digest = str(cached.get("sha256", ""))
            if int(cached.get("size_bytes", -1)) == size_bytes and int(cached.get("output_mtime_ns", -1)) == mtime_ns and len(digest) == 64:
                return digest
        except (TypeError, ValueError):
            pass
        return ""

    def _load_build_state(self, profile: GameProfile) -> dict[str, object]:
        path = self._build_state_path(profile)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) and value.get("version") == 1 else {}

    @staticmethod
    def _source_signature(source: Path) -> str:
        entries = tuple(sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()))
        if any(path.is_symlink() for path in entries):
            raise WorkspaceError(f"不允许符号链接：{source.name}")
        files = tuple(path for path in entries if path.is_file())
        if not files:
            raise WorkspaceError(f"文件夹为空：{source.name}")
        digest = hashlib.sha256()
        for path in files:
            stat = path.stat()
            digest.update(path.relative_to(source).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(stat.st_size).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(stat.st_mtime_ns).encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

    @staticmethod
    def _cached_output_matches(cached: object, source_signature: str, asset_name: str, output: Path) -> bool:
        if not isinstance(cached, dict) or not output.is_file():
            return False
        try:
            stat = output.stat()
            return (
                cached.get("source_signature") == source_signature
                and cached.get("asset_name") == asset_name
                and int(cached.get("size_bytes", -1)) == stat.st_size
                and int(cached.get("output_mtime_ns", -1)) == stat.st_mtime_ns
                and isinstance(cached.get("sha256"), str)
                and len(str(cached["sha256"])) == 64
            )
        except (TypeError, ValueError, OSError):
            return False

    @staticmethod
    def _cached_release_parts(
        cached: object,
        source_signature: str,
        asset_name: str,
        directory: Path,
    ) -> tuple[Path, ...]:
        if not isinstance(cached, dict):
            return ()
        if (
            cached.get("source_signature") != source_signature
            or cached.get("asset_name") != asset_name
            or not isinstance(cached.get("sha256"), str)
            or len(str(cached["sha256"])) != 64
            or not isinstance(cached.get("parts"), list)
            or not cached["parts"]
        ):
            return ()
        parts: list[Path] = []
        try:
            for value in cached["parts"]:
                if not isinstance(value, dict):
                    return ()
                name = str(value.get("asset_name", ""))
                if Path(name).name != name or _RELEASE_PART.fullmatch(name) is None:
                    return ()
                path = directory / name
                stat = path.stat()
                if (
                    not path.is_file()
                    or int(value.get("size_bytes", -1)) != stat.st_size
                    or int(value.get("output_mtime_ns", -1)) != stat.st_mtime_ns
                    or len(str(value.get("sha256", ""))) != 64
                ):
                    return ()
                parts.append(path)
        except (OSError, TypeError, ValueError):
            return ()
        return tuple(parts)

    @staticmethod
    def _existing_zip_matches_source(
        source: Path, output: Path, *, archive_root: str | None = None
    ) -> bool:
        if not output.is_file():
            return False
        files = tuple(sorted((path for path in source.rglob("*") if path.is_file()), key=lambda item: item.relative_to(source).as_posix()))
        if not files or any(path.is_symlink() for path in source.rglob("*")):
            return False
        try:
            if output.stat().st_mtime_ns < max(path.stat().st_mtime_ns for path in files):
                return False
            expected = {
                (Path(archive_root or source.name) / path.relative_to(source)).as_posix(): path.stat().st_size
                for path in files
            }
            with zipfile.ZipFile(output) as archive:
                actual = {item.filename: item.file_size for item in archive.infolist() if not item.is_dir()}
                if len(actual) != len(tuple(item for item in archive.infolist() if not item.is_dir())):
                    return False
            return actual == expected
        except (OSError, zipfile.BadZipFile, ValueError):
            return False

    @staticmethod
    def _appinfo_payload(appinfo: SteamAppInfo) -> dict[str, object]:
        return {
            "app_id": appinfo.app_id,
            "name": appinfo.name,
            "update_time": appinfo.update_time,
            "dlcs": [{"id": item.app_id, "name": item.name} for item in appinfo.dlcs],
        }

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, suffix=".tmp", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temporary = Path(handle.name)
        temporary.replace(path)
