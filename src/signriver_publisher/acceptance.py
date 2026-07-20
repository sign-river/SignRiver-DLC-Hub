from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .models import GameProfile
from .workspace import PublisherWorkspace, WorkspaceError


class AcceptanceError(RuntimeError):
    pass


PENDING = "pending"
PASSED = "passed"
FAILED = "failed"
SKIPPED = "skipped"
VALID_RESULTS = {PASSED, FAILED, SKIPPED}


@dataclass(frozen=True, slots=True)
class AcceptanceCase:
    case_id: str
    category: str
    title: str
    purpose: str
    preparation: tuple[str, ...]
    actions: tuple[str, ...]
    expected: tuple[str, ...]
    recovery: tuple[str, ...]
    download_level: str = "无需下载"

    def instructions(self) -> str:
        sections = (
            ("测试目的", (self.purpose,)),
            ("环境准备", self.preparation),
            ("客户端操作", self.actions),
            ("预期结果", self.expected),
            ("测试后恢复", self.recovery),
        )
        lines = [f"数据量：{self.download_level}"]
        for heading, items in sections:
            lines.extend(("", heading))
            lines.extend(f"{index}. {item}" for index, item in enumerate(items, 1))
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class AcceptanceFingerprint:
    value: str
    client_digest: str
    cartridge_digest: str
    assets_digest: str
    client_path: str
    asset_count: int
    created_at: str

    @property
    def short(self) -> str:
        return self.value[:12]


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    status: str
    updated_at: str
    fingerprint: str
    note: str = ""

    @classmethod
    def from_dict(cls, value: object) -> "AcceptanceResult | None":
        if not isinstance(value, dict) or value.get("status") not in VALID_RESULTS:
            return None
        return cls(
            str(value["status"]),
            str(value.get("updated_at", "")),
            str(value.get("fingerprint", "")),
            str(value.get("note", "")),
        )


@dataclass(slots=True)
class AcceptanceSession:
    session_id: str
    game_id: str
    started_at: str
    fingerprint: AcceptanceFingerprint
    results: dict[str, AcceptanceResult] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: object) -> "AcceptanceSession | None":
        if not isinstance(value, dict) or value.get("version") != 1:
            return None
        raw_fingerprint = value.get("fingerprint")
        if not isinstance(raw_fingerprint, dict):
            return None
        try:
            fingerprint = AcceptanceFingerprint(**raw_fingerprint)
        except (TypeError, ValueError):
            return None
        results: dict[str, AcceptanceResult] = {}
        raw_results = value.get("results")
        if isinstance(raw_results, dict):
            for case_id, raw_result in raw_results.items():
                parsed = AcceptanceResult.from_dict(raw_result)
                if parsed is not None:
                    results[str(case_id)] = parsed
        return cls(
            str(value.get("session_id", "")),
            str(value.get("game_id", "")),
            str(value.get("started_at", "")),
            fingerprint,
            results,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "version": 1,
            "session_id": self.session_id,
            "game_id": self.game_id,
            "started_at": self.started_at,
            "fingerprint": asdict(self.fingerprint),
            "results": {
                case_id: asdict(result) for case_id, result in self.results.items()
            },
        }


@dataclass(frozen=True, slots=True)
class AcceptancePaths:
    client_path: Path | None
    game_path: Path | None


@dataclass(frozen=True, slots=True)
class PreparationVariant:
    variant_id: str
    case_id: str
    label: str
    description: str
    operations: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PreparationPreview:
    variant: PreparationVariant
    actions: tuple[str, ...]
    baseline_path: Path


class AcceptanceManager:
    """Persistent, cartridge-scoped manual release acceptance support."""

    def __init__(
        self, workspace: PublisherWorkspace, *, project_root: Path | None = None
    ) -> None:
        self.workspace = workspace
        self.root = workspace.root / "acceptance"
        self.project_root = (project_root or workspace.root.parent).resolve()
        self._hash_cache: dict[tuple[str, int, int], str] = {}

    def cases_for(self, profile: GameProfile) -> tuple[AcceptanceCase, ...]:
        cases = list(_COMMON_CASES)
        if profile.dlc_archive_root_mode == "strip_id_prefix":
            cases.append(_MAPPED_DLC_CASE)
        return tuple(cases)

    def configured_paths(self, profile: GameProfile) -> AcceptancePaths:
        settings = self._load_settings()
        games = settings.get("games") if isinstance(settings, dict) else None
        game = games.get(profile.game_id) if isinstance(games, dict) else None
        if not isinstance(game, dict):
            game = {}
        client = self._path_or_none(game.get("client_path")) or self.find_default_client()
        actual_game = self._path_or_none(game.get("game_path"))
        return AcceptancePaths(client, actual_game)

    def save_paths(
        self,
        profile: GameProfile,
        *,
        client_path: Path | None = None,
        game_path: Path | None = None,
        keep_client: bool = True,
        keep_game: bool = True,
    ) -> AcceptancePaths:
        settings = self._load_settings()
        games = settings.setdefault("games", {})
        if not isinstance(games, dict):
            games = {}
            settings["games"] = games
        game = games.setdefault(profile.game_id, {})
        if not isinstance(game, dict):
            game = {}
            games[profile.game_id] = game
        if not keep_client:
            game["client_path"] = str(client_path.resolve()) if client_path else ""
        if not keep_game:
            game["game_path"] = str(game_path.resolve()) if game_path else ""
        self._atomic_json(self.root / "settings.json", settings)
        return self.configured_paths(profile)

    @staticmethod
    def patch_directory(
        profile: GameProfile, game_root: Path, *, require_exists: bool = False
    ) -> Path:
        """Resolve the patch directory exclusively from the active cartridge."""
        root = Path(game_root).resolve()
        patch_dir = (root / profile.patch_relative_dir).resolve()
        if not patch_dir.is_relative_to(root):
            raise AcceptanceError(
                f"{profile.display_name} 卡带的补丁目录超出了游戏根目录："
                f"{profile.patch_relative_dir}"
            )
        if require_exists and not patch_dir.is_dir():
            raise AcceptanceError(
                f"{profile.display_name} 卡带配置的补丁目录不存在：\n"
                f"{patch_dir}\n\n"
                "请确认当前选择的是该卡带对应的游戏根目录；如游戏结构已变化，"
                "请先在“卡带配置”中更新补丁安装目录。"
            )
        return patch_dir

    def find_default_client(self) -> Path | None:
        from signriver_launcher.product import (
            BUILD_EXE_BASENAME,
            RELEASE_DIR_NAME,
            RELEASE_EXE_NAME,
        )

        candidates = (
            self.project_root / "dist" / RELEASE_DIR_NAME / RELEASE_EXE_NAME,
            self.project_root / "dist" / "SignRiver-DLC-Hub" / f"{BUILD_EXE_BASENAME}.exe",
            self.project_root / "dist" / RELEASE_EXE_NAME,
            self.project_root / "dist" / f"{BUILD_EXE_BASENAME}.exe",
            self.project_root / "dist" / "bin" / f"{BUILD_EXE_BASENAME}.exe",
            self.project_root / RELEASE_EXE_NAME,
            self.project_root / f"{BUILD_EXE_BASENAME}.exe",
        )
        return next((path.resolve() for path in candidates if path.is_file()), None)

    def fingerprint(
        self, profile: GameProfile, client_path: Path | None
    ) -> AcceptanceFingerprint:
        cartridge_payload = json.dumps(
            profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        cartridge_digest = hashlib.sha256(cartridge_payload).hexdigest()
        client_digest = self._client_digest(client_path)
        try:
            assets = self.workspace.publish_assets(profile)
            asset_lines = [
                f"{asset.name}\0{asset.size_bytes}\0{asset.sha256}" for asset in assets
            ]
        except (OSError, WorkspaceError):
            target = self.workspace.output_dir / profile.game_id
            files = (
                tuple(sorted(path for path in target.iterdir() if path.is_file()))
                if target.is_dir()
                else ()
            )
            asset_lines = [
                f"{path.name}\0{path.stat().st_size}\0{self._file_digest(path)}"
                for path in files
            ]
        assets_digest = hashlib.sha256("\n".join(asset_lines).encode("utf-8")).hexdigest()
        combined = hashlib.sha256(
            f"{client_digest}\n{cartridge_digest}\n{assets_digest}".encode("ascii")
        ).hexdigest()
        return AcceptanceFingerprint(
            combined,
            client_digest,
            cartridge_digest,
            assets_digest,
            str(client_path.resolve()) if client_path else "",
            len(asset_lines),
            self._now(),
        )

    def current_session(self, profile: GameProfile) -> AcceptanceSession | None:
        path = self._current_session_path(profile)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        session = AcceptanceSession.from_dict(value)
        return session if session and session.game_id == profile.game_id else None

    def ensure_session(
        self, profile: GameProfile, fingerprint: AcceptanceFingerprint
    ) -> AcceptanceSession:
        return self.current_session(profile) or self.new_session(profile, fingerprint)

    def new_session(
        self, profile: GameProfile, fingerprint: AcceptanceFingerprint
    ) -> AcceptanceSession:
        session = AcceptanceSession(
            datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
            + "-"
            + uuid.uuid4().hex[:6],
            profile.game_id,
            self._now(),
            fingerprint,
        )
        current = self._current_session_path(profile)
        old = self.current_session(profile)
        if old is not None:
            self._atomic_json(self._history_dir(profile) / f"{old.session_id}.json", old.to_dict())
        self._atomic_json(current, session.to_dict())
        return session

    def record_result(
        self,
        profile: GameProfile,
        case_id: str,
        status: str,
        current_fingerprint: AcceptanceFingerprint,
        *,
        note: str = "",
    ) -> AcceptanceSession:
        if status not in VALID_RESULTS:
            raise AcceptanceError("不支持的验收结果")
        session = self.ensure_session(profile, current_fingerprint)
        if session.fingerprint.value != current_fingerprint.value:
            raise AcceptanceError("客户端、卡带或发布资源已经变化，请先开始新一轮验收")
        known = {case.case_id for case in self.cases_for(profile)}
        if case_id not in known:
            raise AcceptanceError("验收项目不存在")
        session.results[case_id] = AcceptanceResult(
            status, self._now(), current_fingerprint.value, note.strip()
        )
        self._atomic_json(self._current_session_path(profile), session.to_dict())
        return session

    def clear_result(
        self, profile: GameProfile, case_id: str
    ) -> AcceptanceSession | None:
        session = self.current_session(profile)
        if session is None:
            return None
        session.results.pop(case_id, None)
        self._atomic_json(self._current_session_path(profile), session.to_dict())
        return session

    @staticmethod
    def preparation_variants(case_id: str) -> tuple[PreparationVariant, ...]:
        return _PREPARATION_VARIANTS.get(case_id, ())

    def current_baseline(
        self, profile: GameProfile, session: AcceptanceSession
    ) -> dict[str, object] | None:
        return self._load_json(self._baseline_path(profile, session.session_id), version=1)

    def capture_patch_baseline(
        self,
        profile: GameProfile,
        paths: AcceptancePaths,
        session: AcceptanceSession,
        fingerprint: AcceptanceFingerprint,
        *,
        overwrite: bool = False,
    ) -> Path:
        self._validate_acceptance_context(profile, paths, session, fingerprint)
        if self.active_preparation(profile) is not None:
            raise AcceptanceError("当前游戏存在尚未恢复的测试环境，请先恢复环境")
        targets = self._patch_targets(profile, paths)
        destination = self._baseline_dir(profile, session.session_id)
        if destination.exists() and not overwrite:
            raise AcceptanceError("当前轮次已经记录补丁基线")
        staging = destination.parent / f".{destination.name}-{uuid.uuid4().hex[:8]}.tmp"
        if staging.exists():
            shutil.rmtree(staging)
        files_dir = staging / "files"
        files_dir.mkdir(parents=True)
        files: dict[str, object] = {}
        assert paths.game_path is not None
        game_root = paths.game_path.resolve()
        try:
            for key, target in targets.items():
                if target.is_symlink():
                    raise AcceptanceError(f"测试目标不允许是符号链接：{target}")
                if target.exists() and not target.is_file():
                    raise AcceptanceError(f"测试目标不是普通文件：{target}")
                existed = target.is_file()
                backup_name = f"{key}.bin"
                entry: dict[str, object] = {
                    "relative_path": target.relative_to(game_root).as_posix(),
                    "existed": existed,
                    "backup_name": backup_name if existed else "",
                    "size_bytes": target.stat().st_size if existed else 0,
                    "sha256": self._read_digest(target) if existed else "",
                }
                if existed:
                    shutil.copy2(target, files_dir / backup_name)
                files[key] = entry
            self._atomic_json(
                staging / "baseline.json",
                {
                    "version": 1,
                    "game_id": profile.game_id,
                    "session_id": session.session_id,
                    "fingerprint": fingerprint.value,
                    "game_path": str(game_root),
                    "created_at": self._now(),
                    "files": files,
                },
            )
            if destination.exists():
                shutil.rmtree(destination)
            staging.replace(destination)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        return destination / "baseline.json"

    def preview_preparation(
        self,
        profile: GameProfile,
        paths: AcceptancePaths,
        session: AcceptanceSession,
        fingerprint: AcceptanceFingerprint,
        case_id: str,
        variant_id: str,
    ) -> PreparationPreview:
        self._validate_acceptance_context(profile, paths, session, fingerprint)
        if self.active_preparation(profile) is not None:
            raise AcceptanceError("当前游戏存在尚未恢复的测试环境，请先恢复环境")
        variant = self._variant(case_id, variant_id)
        baseline_path = self._baseline_path(profile, session.session_id)
        baseline = self._load_json(baseline_path, version=1)
        if baseline is None:
            raise AcceptanceError("请先记录当前轮次的补丁环境基线")
        self._validate_baseline(
            profile, paths, session, fingerprint, baseline_path, baseline
        )
        files = baseline.get("files")
        if not isinstance(files, dict):
            raise AcceptanceError("补丁环境基线缺少文件记录")
        actions: list[str] = []
        assert paths.game_path is not None
        for key, operation in variant.operations:
            entry = files.get(key)
            if not isinstance(entry, dict):
                raise AcceptanceError(f"补丁环境基线缺少目标：{key}")
            target = paths.game_path.resolve() / str(entry["relative_path"])
            if operation == "remove":
                actions.append(f"暂时移除：{target}")
            elif operation == "replace_marker":
                actions.append(f"替换为无效测试文件：{target}")
            else:
                raise AcceptanceError(f"不支持的环境准备动作：{operation}")
        return PreparationPreview(variant, tuple(actions), baseline_path)

    def apply_preparation(
        self,
        profile: GameProfile,
        paths: AcceptancePaths,
        session: AcceptanceSession,
        fingerprint: AcceptanceFingerprint,
        case_id: str,
        variant_id: str,
    ) -> PreparationPreview:
        preview = self.preview_preparation(
            profile, paths, session, fingerprint, case_id, variant_id
        )
        baseline = self._load_json(preview.baseline_path, version=1)
        if baseline is None:
            raise AcceptanceError("补丁环境基线不可用")
        self._verify_environment_matches_baseline(paths, preview.baseline_path, baseline)
        files = baseline["files"]
        assert isinstance(files, dict)
        assert paths.game_path is not None
        prepared_path = self._prepared_path(profile)
        prepared_payload = {
            "version": 1,
            "game_id": profile.game_id,
            "session_id": session.session_id,
            "fingerprint": fingerprint.value,
            "game_path": str(paths.game_path.resolve()),
            "case_id": case_id,
            "variant_id": variant_id,
            "variant_label": preview.variant.label,
            "baseline_path": str(preview.baseline_path.resolve()),
            "applied_at": self._now(),
            "status": "applying",
            "actions": list(preview.actions),
        }
        self._atomic_json(prepared_path, prepared_payload)
        try:
            for key, operation in preview.variant.operations:
                entry = files[key]
                assert isinstance(entry, dict)
                target = paths.game_path.resolve() / str(entry["relative_path"])
                if target.is_symlink() or (target.exists() and not target.is_file()):
                    raise AcceptanceError(f"测试目标不再是安全的普通文件：{target}")
                if operation == "remove":
                    target.unlink(missing_ok=True)
                elif operation == "replace_marker":
                    self._atomic_bytes(
                        target,
                        b"SIGNRIVER ACCEPTANCE TEST FILE\r\n"
                        b"This is intentionally not a usable DLL.\r\n",
                    )
            prepared_payload["status"] = "applied"
            self._atomic_json(prepared_path, prepared_payload)
        except Exception as error:
            try:
                self._restore_baseline_data(preview.baseline_path, baseline)
                prepared_path.unlink(missing_ok=True)
            except Exception as restore_error:
                raise AcceptanceError(
                    f"准备测试环境失败，自动恢复也失败：{error}；{restore_error}"
                ) from error
            if isinstance(error, AcceptanceError):
                raise
            raise AcceptanceError(f"准备测试环境失败，已恢复基线：{error}") from error
        return preview

    def active_preparation(self, profile: GameProfile) -> dict[str, object] | None:
        return self._load_json(self._prepared_path(profile), version=1)

    def active_preparations(self) -> tuple[dict[str, object], ...]:
        if not self.root.is_dir():
            return ()
        values: list[dict[str, object]] = []
        for path in self.root.glob("*/prepared.json"):
            value = self._load_json(path, version=1)
            if value is not None:
                values.append(value)
        return tuple(values)

    def restore_prepared_environment(self, profile: GameProfile) -> int:
        prepared_path = self._prepared_path(profile)
        prepared = self._load_json(prepared_path, version=1)
        if prepared is None:
            raise AcceptanceError("当前游戏没有待恢复的测试环境")
        baseline_text = str(prepared.get("baseline_path", ""))
        baseline_path = Path(baseline_text).resolve() if baseline_text else None
        if baseline_path is None or not baseline_path.is_relative_to(self.root.resolve()):
            raise AcceptanceError("测试环境记录中的基线路径不安全")
        baseline = self._load_json(baseline_path, version=1)
        if baseline is None:
            raise AcceptanceError("无法读取测试前补丁基线，已停止恢复")
        count = self._restore_baseline_data(baseline_path, baseline)
        prepared_path.unlink(missing_ok=True)
        return count

    def evidence_dir(
        self, profile: GameProfile, session: AcceptanceSession
    ) -> Path:
        path = self._evidence_dir(profile, session)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def inspect_environment(
        self,
        profile: GameProfile,
        paths: AcceptancePaths,
        session: AcceptanceSession,
    ) -> tuple[Path, dict[str, object]]:
        game_root = paths.game_path
        dlc_dir = game_root / profile.dlc_relative_dir if game_root else None
        patch_dir = (
            self.patch_directory(profile, game_root)
            if game_root else None
        )
        dlc_folders = (
            sorted(path.name for path in dlc_dir.iterdir() if path.is_dir())
            if dlc_dir and dlc_dir.is_dir()
            else []
        )
        patch_files: dict[str, object] = {}
        for name in (*profile.patch_asset_names, "cream_api.ini"):
            path = patch_dir / name if patch_dir else None
            patch_files[name] = self._file_summary(path)
        log_path = self.find_client_log(paths.client_path)
        report: dict[str, object] = {
            "version": 1,
            "recorded_at": self._now(),
            "game_id": profile.game_id,
            "session_id": session.session_id,
            "client": self._file_summary(paths.client_path),
            "game_root": self._directory_summary(game_root),
            "dlc_directory": self._directory_summary(dlc_dir),
            "dlc_folder_count": len(dlc_folders),
            "dlc_folder_sample": dlc_folders[:30],
            "patch_directory": self._directory_summary(patch_dir),
            "patch_files": patch_files,
            "client_log": self._file_summary(log_path),
        }
        output = self._evidence_dir(profile, session) / f"environment-{self._timestamp()}.json"
        self._atomic_json(output, report)
        return output, report

    def collect_client_log(
        self,
        profile: GameProfile,
        paths: AcceptancePaths,
        session: AcceptanceSession,
    ) -> Path:
        source = self.find_client_log(paths.client_path)
        if source is None or not source.is_file():
            raise AcceptanceError("未找到客户端日志，请先选择实际运行的客户端 EXE")
        target = self._evidence_dir(profile, session) / f"launcher-{self._timestamp()}.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    @staticmethod
    def find_client_log(client_path: Path | None) -> Path | None:
        if client_path is None:
            return None
        roots = (client_path.parent, client_path.parent.parent)
        return next(
            (
                root / "data" / "logs" / "launcher.log"
                for root in roots
                if (root / "data" / "logs" / "launcher.log").is_file()
            ),
            roots[0] / "data" / "logs" / "launcher.log",
        )

    def _client_digest(self, client_path: Path | None) -> str:
        if client_path is None or not client_path.is_file():
            return hashlib.sha256(b"missing-client").hexdigest()
        root = client_path.parent
        if root.name.casefold() == "bin" and (root.parent / "app").is_dir():
            root = root.parent
        relevant = [client_path]
        state = root / "app" / "state.json"
        if state.is_file():
            relevant.append(state)
        versions = root / "app" / "versions"
        if versions.is_dir():
            relevant.extend(path for path in versions.rglob("*") if path.is_file())
        digest = hashlib.sha256()
        for path in sorted(set(relevant), key=lambda item: str(item).casefold()):
            digest.update(str(path.relative_to(root) if path.is_relative_to(root) else path.name).encode("utf-8"))
            digest.update(b"\0")
            digest.update(self._file_digest(path).encode("ascii"))
            digest.update(b"\n")
        return digest.hexdigest()

    def _validate_acceptance_context(
        self,
        profile: GameProfile,
        paths: AcceptancePaths,
        session: AcceptanceSession,
        fingerprint: AcceptanceFingerprint,
    ) -> None:
        if session.game_id != profile.game_id:
            raise AcceptanceError("验收轮次与当前游戏不匹配")
        if session.fingerprint.value != fingerprint.value:
            raise AcceptanceError("当前构建已经变化，请先开始新一轮验收")
        if paths.game_path is None or not paths.game_path.is_dir():
            raise AcceptanceError("请先选择当前游戏的实际安装目录")

    def _patch_targets(
        self, profile: GameProfile, paths: AcceptancePaths
    ) -> dict[str, Path]:
        assert paths.game_path is not None
        game_root = paths.game_path.resolve()
        patch_dir = self.patch_directory(
            profile, game_root, require_exists=True
        )
        return {
            "unlocker": patch_dir / profile.patch_unlocker_name,
            "backup": patch_dir / profile.patch_original_backup_name,
            "ini": patch_dir / "cream_api.ini",
        }

    @staticmethod
    def _variant(case_id: str, variant_id: str) -> PreparationVariant:
        for variant in _PREPARATION_VARIANTS.get(case_id, ()):
            if variant.variant_id == variant_id:
                return variant
        raise AcceptanceError("当前验收项目没有这个环境方案")

    def _validate_baseline(
        self,
        profile: GameProfile,
        paths: AcceptancePaths,
        session: AcceptanceSession,
        fingerprint: AcceptanceFingerprint,
        baseline_path: Path,
        baseline: dict[str, object],
    ) -> None:
        assert paths.game_path is not None
        if baseline.get("game_id") != profile.game_id:
            raise AcceptanceError("补丁环境基线属于另一款游戏")
        if baseline.get("session_id") != session.session_id:
            raise AcceptanceError("补丁环境基线不属于当前验收轮次")
        if baseline.get("fingerprint") != fingerprint.value:
            raise AcceptanceError("补丁环境基线对应的构建已经过期")
        if Path(str(baseline.get("game_path", ""))).resolve() != paths.game_path.resolve():
            raise AcceptanceError("补丁环境基线对应的是另一个游戏目录")
        if not baseline_path.resolve().is_relative_to(self.root.resolve()):
            raise AcceptanceError("补丁环境基线路径不安全")

    def _verify_environment_matches_baseline(
        self,
        paths: AcceptancePaths,
        baseline_path: Path,
        baseline: dict[str, object],
    ) -> None:
        assert paths.game_path is not None
        files = baseline.get("files")
        if not isinstance(files, dict):
            raise AcceptanceError("补丁环境基线缺少文件记录")
        for entry in files.values():
            if not isinstance(entry, dict):
                raise AcceptanceError("补丁环境基线格式不正确")
            target = paths.game_path.resolve() / str(entry.get("relative_path", ""))
            existed = bool(entry.get("existed"))
            if existed != target.is_file():
                raise AcceptanceError(
                    f"记录基线后环境已经变化，请重新记录基线：{target.name}"
                )
            if existed and self._read_digest(target) != entry.get("sha256"):
                raise AcceptanceError(
                    f"记录基线后文件内容已经变化，请重新记录基线：{target.name}"
                )
            if existed:
                backup = baseline_path.parent / "files" / str(entry.get("backup_name", ""))
                if not backup.is_file() or self._read_digest(backup) != entry.get("sha256"):
                    raise AcceptanceError(f"补丁基线备份损坏：{target.name}")

    def _restore_baseline_data(
        self, baseline_path: Path, baseline: dict[str, object]
    ) -> int:
        game_root = Path(str(baseline.get("game_path", ""))).resolve()
        if not game_root.is_dir():
            raise AcceptanceError("原游戏目录不存在，无法恢复测试环境")
        files = baseline.get("files")
        if not isinstance(files, dict):
            raise AcceptanceError("补丁环境基线缺少文件记录")
        restored = 0
        for entry in files.values():
            if not isinstance(entry, dict):
                raise AcceptanceError("补丁环境基线格式不正确")
            target = (game_root / str(entry.get("relative_path", ""))).resolve()
            if not target.is_relative_to(game_root):
                raise AcceptanceError("补丁环境基线包含越界路径")
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise AcceptanceError(f"拒绝覆盖非普通文件：{target}")
            if bool(entry.get("existed")):
                backup = baseline_path.parent / "files" / str(entry.get("backup_name", ""))
                if not backup.is_file() or self._read_digest(backup) != entry.get("sha256"):
                    raise AcceptanceError(f"补丁基线备份损坏：{target.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_name(
                    f".{target.name}.acceptance-{uuid.uuid4().hex[:8]}.tmp"
                )
                try:
                    shutil.copy2(backup, temporary)
                    os.replace(temporary, target)
                finally:
                    temporary.unlink(missing_ok=True)
            else:
                target.unlink(missing_ok=True)
            restored += 1
        return restored

    def _file_digest(self, path: Path) -> str:
        stat = path.stat()
        key = (str(path.resolve()).casefold(), stat.st_size, stat.st_mtime_ns)
        cached = self._hash_cache.get(key)
        if cached:
            return cached
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        self._hash_cache[key] = value
        return value

    @staticmethod
    def _read_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load_settings(self) -> dict[str, object]:
        path = self.root / "settings.json"
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"version": 1, "games": {}}
        if not isinstance(value, dict) or value.get("version") != 1:
            return {"version": 1, "games": {}}
        return value

    @staticmethod
    def _load_json(path: Path, *, version: int) -> dict[str, object] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) and value.get("version") == version else None

    @staticmethod
    def _path_or_none(value: object) -> Path | None:
        text = str(value or "").strip()
        return Path(text).expanduser().resolve() if text else None

    def _game_root(self, profile: GameProfile) -> Path:
        return self.root / profile.game_id

    def _baseline_dir(self, profile: GameProfile, session_id: str) -> Path:
        return self._game_root(profile) / "baselines" / session_id

    def _baseline_path(self, profile: GameProfile, session_id: str) -> Path:
        return self._baseline_dir(profile, session_id) / "baseline.json"

    def _prepared_path(self, profile: GameProfile) -> Path:
        return self._game_root(profile) / "prepared.json"

    def _current_session_path(self, profile: GameProfile) -> Path:
        return self._game_root(profile) / "current.json"

    def _history_dir(self, profile: GameProfile) -> Path:
        return self._game_root(profile) / "history"

    def _evidence_dir(
        self, profile: GameProfile, session: AcceptanceSession
    ) -> Path:
        return self._game_root(profile) / "evidence" / session.session_id

    @staticmethod
    def _file_summary(path: Path | None) -> dict[str, object]:
        if path is None:
            return {"path": "", "exists": False}
        summary: dict[str, object] = {"path": str(path), "exists": path.is_file()}
        if path.is_file():
            stat = path.stat()
            summary.update(size_bytes=stat.st_size, modified_ns=stat.st_mtime_ns)
        return summary

    @staticmethod
    def _directory_summary(path: Path | None) -> dict[str, object]:
        if path is None:
            return {"path": "", "exists": False}
        return {"path": str(path), "exists": path.is_dir()}

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")

    @staticmethod
    def _atomic_json(path: Path, value: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _atomic_bytes(path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


_PREPARATION_VARIANTS = {
    "patch.clean-install": (
        PreparationVariant(
            "patch.clean-original",
            "patch.clean-install",
            "首次安装：仅保留当前 DLL",
            "暂时移走原版备份 DLL 和 cream_api.ini，用于验证只有当前原版 DLL 的首次安装流程。",
            (("backup", "remove"), ("ini", "remove")),
        ),
    ),
    "patch.damaged-state": (
        PreparationVariant(
            "patch.current-missing",
            "patch.damaged-state",
            "当前 DLL 缺失",
            "暂时移走当前 DLL，验证客户端对缺失主文件的处理。",
            (("unlocker", "remove"),),
        ),
        PreparationVariant(
            "patch.backup-missing",
            "patch.damaged-state",
            "原版备份 DLL 缺失",
            "暂时移走原版备份 DLL，验证客户端不会伪造不可信备份。",
            (("backup", "remove"),),
        ),
        PreparationVariant(
            "patch.ini-missing",
            "patch.damaged-state",
            "INI 文件缺失",
            "暂时移走 cream_api.ini，验证客户端能否根据当前 AppInfo 重新生成。",
            (("ini", "remove"),),
        ),
        PreparationVariant(
            "patch.current-mismatch",
            "patch.damaged-state",
            "当前 DLL 内容异常",
            "把当前 DLL 替换为明显无效的测试文件，验证异常同名文件的修复和提示。",
            (("unlocker", "replace_marker"),),
        ),
    ),
}


_COMMON_CASES = (
    AcceptanceCase(
        "basic.game-detection",
        "基础",
        "游戏路径与卡带切换",
        "确认客户端能识别当前游戏，并且切换卡带后不会沿用上一款游戏的路径和状态。",
        ("在验收页选择当前游戏的实际安装目录。", "准备至少另一张已配置卡带用于往返切换。"),
        ("启动客户端并确认自动识别路径。", "切换到另一款游戏，再切回当前游戏。"),
        ("游戏名称、Steam App ID、DLC 目录和补丁目录均属于当前卡带。", "切换后列表和安装状态没有串到另一款游戏。"),
        ("无需修改游戏文件。",),
    ),
    AcceptanceCase(
        "dlc.native-preservation",
        "DLC",
        "原有 DLC 识别与保留",
        "确认游戏自带或其他来源的 DLC 能被识别，并且安全恢复不会误删。",
        ("记录游戏 DLC 目录当前文件夹数量和名称。", "选择一个不是本程序刚安装的原有 DLC 作为观察对象。"),
        ("刷新 DLC 目录。", "执行“恢复游戏原版”，随后再次刷新。"),
        ("原有 DLC 显示为已安装。", "安全恢复后观察对象仍然存在，游戏可以正常启动。"),
        ("如结果异常，停止后续测试并用测试前备份恢复。",),
    ),
    AcceptanceCase(
        "dlc.partial-and-persistence",
        "DLC",
        "部分安装与重启识别",
        "验证只安装部分 DLC 时的状态，以及关闭客户端后安装记录是否持久化。",
        ("只勾选少量未安装 DLC。",),
        ("执行一键解锁并等待这些 DLC 安装完成。", "关闭并重新打开客户端。"),
        ("选中的 DLC 变为已安装，其他未选内容不受影响。", "重启后状态仍然正确。"),
        ("按需要卸载本轮安装的测试 DLC。",),
        "少量下载",
    ),
    AcceptanceCase(
        "download.pause-cancel-restart",
        "下载",
        "暂停、继续、取消与重启",
        "确认顺序下载在暂停、继续、取消和客户端重启时不会留下错误任务或半包。",
        ("选择一个下载时间足够观察状态变化的 DLC。",),
        ("开始下载，依次测试暂停和继续。", "再次下载时执行取消全部任务。", "关闭并重启客户端检查任务列表。"),
        ("暂停后当前半包被清理，已完成 DLC 保留。", "继续时从当前 DLC 重新下载。", "取消后可重新选择，重启后不会复活已清除记录。"),
        ("清除失败/取消记录和不再需要的缓存。",),
        "中等下载",
    ),
    AcceptanceCase(
        "download.cache-reuse",
        "下载",
        "缓存复用",
        "确认已经完整下载过的相同附件可以从缓存重新安装。",
        ("准备一个已完整下载并安装的 DLC。", "记录客户端缓存大小。"),
        ("卸载该 DLC，但不要清理缓存。", "再次选择并安装同一 DLC。"),
        ("第二次安装能直接复用缓存。", "安装结果完整，任务状态没有误报下载失败。"),
        ("保留或按需要清理测试缓存。",),
        "应无需重新下载",
    ),
    AcceptanceCase(
        "download.multipart",
        "下载",
        "分卷资源下载与重组",
        "验证大于单附件限制的 DLC 能完整下载所有分卷并重组成可安装包。",
        ("在当前 Release 中确认测试 DLC 具有连续分卷。", "确保磁盘空间足够容纳分卷、重组包和安装内容。"),
        ("选择该 DLC 并执行一键解锁。", "观察下载任务直到安装结束。"),
        ("所有分卷按顺序完成并只产生一个安装结果。", "缺卷、错序或重组失败时不会安装半成品。"),
        ("按需要卸载本轮测试 DLC；大缓存可在验收结束后统一清理。",),
        "大量下载",
    ),
    AcceptanceCase(
        "patch.clean-install",
        "补丁",
        "原版环境首次应用补丁",
        "验证只有原版 DLL 的干净环境可以完成补丁安装和 INI 生成。",
        ("确认游戏补丁目录处于可信原版状态。", "记录相关 DLL 和 cream_api.ini 的当前状态。"),
        ("启动客户端并执行一键解锁。",),
        ("原版 DLL 被安全保留为备份。", "新补丁 DLL 与 cream_api.ini 完整写入，客户端提示解锁成功。"),
        ("使用“一键移除补丁”或“恢复游戏原版”还原。",),
    ),
    AcceptanceCase(
        "patch.damaged-state",
        "补丁",
        "补丁缺失或同名文件异常",
        "验证 DLL 缺失、备份缺失或同名文件内容异常时能够给出明确处理结果。",
        ("先在外部安全位置完整备份补丁目录。", "一次只构造一种异常，记录被移动或替换的文件。"),
        ("对每种异常分别启动客户端并执行一键解锁。", "检查客户端提示和日志。"),
        ("可修复状态被替换为当前可信资源。", "无法确认原版来源时不会伪造原版备份，并给出可理解提示。"),
        ("每种异常测试结束后恢复完整备份，再准备下一种。",),
    ),
    AcceptanceCase(
        "patch.security-quarantine",
        "补丁",
        "安全软件隔离补丁",
        "确认补丁在下载后或应用后被安全软件移除时，客户端不会误报成功。",
        ("保留游戏和补丁目录备份。", "由测试人员在安全软件中手动构造隔离场景，不由发布器自动操作安全软件。"),
        ("执行一键解锁。", "检查失败提示、任务状态和日志。"),
        ("客户端明确提示补丁文件不可用或疑似被隔离。", "DLC 下载不会掩盖补丁失败，目录中不留下半套补丁。"),
        ("按安全软件流程恢复或重新下载文件，然后恢复测试基线。",),
    ),
    AcceptanceCase(
        "recovery.safe-restore",
        "恢复",
        "安全恢复游戏原版",
        "确认安全恢复只撤销本程序有安装记录的内容，并恢复可信原版 DLL。",
        ("准备同时包含原有 DLC 和本程序安装 DLC 的环境。", "记录两类 DLC 与补丁文件状态。"),
        ("执行“恢复游戏原版”并确认提示。",),
        ("程序记录的 DLC 被撤销，被替换内容得到恢复。", "原有 DLC 和其他来源内容保留，原版 DLL 恢复。"),
        ("如需继续测试，可重新执行一键解锁。",),
    ),
    AcceptanceCase(
        "recovery.full-repair",
        "恢复",
        "一键修复完整重建",
        "验证一键修复在明确警告后清理目标内容，并从当前仓库重新构建完整状态。",
        ("确认网络、磁盘空间和测试时间足够。", "记录游戏目录和缓存状态。"),
        ("点击一键修复并阅读大流量提示。", "确认后等待补丁与全部 DLC 完成。"),
        ("补丁使用当前资源完整重建。", "仓库提供的全部 DLC 均重新安装，最终弹出成功提示。"),
        ("该场景会产生大量下载；测试结束后按需要保留或安全恢复。",),
        "大量下载",
    ),
    AcceptanceCase(
        "ui.navigation-refresh",
        "界面",
        "分页、滚动与实时刷新",
        "确认切换页面和下载刷新时不会出现空白列表、滚动位置异常或整页闪烁。",
        ("确保 DLC、下载任务和日志页面都有可显示内容。",),
        ("反复切换简洁/高级模式及各分页。", "下载过程中打开任务页并观察数字更新。", "刷新带滚动条的列表。"),
        ("列表首次显示即位于顶部且内容完整。", "下载中只更新必要字段，完成时才重建对应列表。"),
        ("无需修改游戏文件。",),
    ),
)


_MAPPED_DLC_CASE = AcceptanceCase(
    "dlc.mapped-directory-names",
    "DLC",
    "编号附件与游戏目录映射",
    "验证服务端管理编号不会成为游戏内实际 DLC 文件夹名。",
    ("从验收页记录当前 DLC 目录名称。", "选择一个附件名带 dlcNNN_ 前缀的资源。"),
    ("安装该 DLC 并刷新目录。", "重启客户端再次检查安装状态。"),
    ("下载附件保留管理编号。", "游戏目录使用去掉管理编号后的原始名称，并能被客户端识别为已安装。"),
    ("按需要卸载本轮安装的测试 DLC。",),
    "少量或中等下载",
)


__all__ = [
    "AcceptanceCase",
    "AcceptanceError",
    "AcceptanceFingerprint",
    "AcceptanceManager",
    "AcceptancePaths",
    "AcceptanceResult",
    "AcceptanceSession",
    "PreparationPreview",
    "PreparationVariant",
    "FAILED",
    "PASSED",
    "PENDING",
    "SKIPPED",
]
