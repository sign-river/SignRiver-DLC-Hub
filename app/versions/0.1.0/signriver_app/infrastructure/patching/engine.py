"""Fail-closed, transactional patch lifecycle for one game installation.

Published bundles contain only the program-provided proxy library and AppInfo.
The game-owned original library is captured from the current installation into
``data/original-libraries/v1`` and is later resolved from that persistent vault
(or from a credential-matching runtime ``_o`` copy).  Applying a patch deploys
the verified runtime original and configuration before atomically replacing the
primary library with the proxy.  Removing a patch restores and verifies the
primary library first, then deletes only credential-matching managed files.

All destructive operations are serialized by a per-installation cross-process
lock.  File changes use same-filesystem temporary files and ``os.replace``;
transaction backups support rollback, while a verified vault entry is retained
across repairs and process restarts.  Ambiguous or missing original libraries
are never guessed, replaced, or deleted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from functools import wraps
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ...domain.patches import (
    PatchAudit,
    PatchConfigFormat,
    PatchHealth,
    PatchProfile,
    PatchReceipt,
    PatchTemplate,
)
from ...domain.paths import resolve_game_directory
from .original_library import (
    OriginalLibraryEntry,
)


# Any AppInfo JSON above this size is almost certainly malformed or hostile;
# refuse to parse it instead of turning it into a giant string in memory.
MAX_APPINFO_BYTES = 4 * 1024 * 1024

# 128 MiB gives us plenty of headroom for a CreamAPI DLL (currently ~200 KiB)
# but stops the engine from copying pathological files into game directories.
MAX_PATCH_DLL_BYTES = 128 * 1024 * 1024

_SANE_ID = re.compile(r"^\d{1,20}$")

# UTF-8 BOM.  CreamAPI's loader tolerates either encoding, but Windows text
# editors expect the BOM before rendering multi-byte DLC names correctly.
_UTF8_BOM = b"\xef\xbb\xbf"


class PatchError(RuntimeError):
    """Raised when a patch operation cannot complete safely."""


def _with_installation_lock(method):
    """Serialize destructive operations for one game installation."""
    @wraps(method)
    def locked(self, game_root, *args, **kwargs):
        with self._installation_lock(Path(game_root)):
            return method(self, game_root, *args, **kwargs)
    return locked


@dataclass(frozen=True, slots=True)
class PatchApplyResult:
    """What ``PatchEngine.apply`` actually did, exposed for UI feedback."""

    receipt: PatchReceipt
    audit_before: PatchAudit
    audit_after: PatchAudit
    unlocker_replaced: bool
    backup_created: bool
    backup_replaced: bool
    ini_written: bool
    interference_files_deleted: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PatchRestoreReadiness:
    """Whether the current patch layout can be restored without guessing."""

    ready: bool
    patch_detected: bool
    backup_available: bool
    reason: str = ""


def _ini_bool(value: bool) -> str:
    return "True" if value else "False"


def _looks_like_binary(data: bytes) -> bool:
    """True for PE (MZ), ELF or Mach-O payloads used by Steam API libraries."""
    if data.startswith(b"MZ"):
        return True
    if data.startswith(b"\x7fELF"):
        return True
    return any(
        data.startswith(magic)
        for magic in (
            b"\xfe\xed\xfa\xce",  # MH_MAGIC
            b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64
            b"\xce\xfa\xed\xfe",  # MH_CIGAM
            b"\xcf\xfa\xed\xfe",  # MH_CIGAM_64
            b"\xca\xfe\xba\xbe",  # FAT_MAGIC
            b"\xbe\xba\xfe\xca",  # FAT_CIGAM
        )
    )


def parse_appinfo_document(data: bytes | str) -> Mapping[str, object]:
    """Return the sanitized ``{app_id, dlcs}`` payload from an AppInfo file."""
    if isinstance(data, bytes):
        if len(data) > MAX_APPINFO_BYTES:
            raise PatchError("AppInfo JSON 过大，可能已损坏")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise PatchError("AppInfo JSON 编码不是 UTF-8") from error
    else:
        text = data
    try:
        value = json.loads(text)
    except (ValueError, json.JSONDecodeError) as error:
        raise PatchError(f"AppInfo JSON 无法解析：{error}") from error
    if not isinstance(value, dict):
        raise PatchError("AppInfo JSON 顶层必须是对象")
    app_id = str(value.get("app_id") or "").strip()
    if not _SANE_ID.fullmatch(app_id):
        raise PatchError("AppInfo JSON 缺少有效的 app_id")
    raw_dlcs = value.get("dlcs")
    if not isinstance(raw_dlcs, list):
        raise PatchError("AppInfo JSON 缺少 dlcs 列表")
    dlcs: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in raw_dlcs:
        if not isinstance(entry, dict):
            raise PatchError("AppInfo JSON 中包含非法的 DLC 条目")
        dlc_id = str(entry.get("id") or "").strip()
        name = str(entry.get("name") or "").strip()
        if not _SANE_ID.fullmatch(dlc_id):
            raise PatchError(f"AppInfo JSON 中的 DLC ID 非法：{entry.get('id')!r}")
        if not name or "\r" in name or "\n" in name:
            raise PatchError(f"AppInfo JSON 中的 DLC 名称非法：{entry.get('name')!r}")
        if dlc_id in seen:
            continue
        seen.add(dlc_id)
        dlcs.append({"id": dlc_id, "name": name})
    return {"app_id": app_id, "dlcs": tuple(dlcs)}


def render_cream_api_ini(
    appinfo: Mapping[str, object],
    template: PatchTemplate,
) -> str:
    """Render ``cream_api.ini`` from an AppInfo document and template.

    Mirrors the field layout used by the publisher so the two components stay
    interchangeable without cross-package imports.
    """
    app_id = str(appinfo.get("app_id") or "").strip()
    if not _SANE_ID.fullmatch(app_id):
        raise PatchError("AppInfo 缺少有效的 app_id")
    raw_dlcs = appinfo.get("dlcs")
    if not isinstance(raw_dlcs, (list, tuple)):
        raise PatchError("AppInfo 缺少 dlcs 列表")
    lines = [
        "[steam]",
        f"appid = {app_id}",
        f"language = {template.language}",
        f"unlockall = {_ini_bool(template.unlock_all)}",
        f"extraprotection = {_ini_bool(template.extra_protection)}",
        f"forceoffline = {_ini_bool(template.force_offline)}",
        "",
        "[dlc]",
    ]
    seen: set[str] = set()
    for entry in raw_dlcs:
        if not isinstance(entry, Mapping):
            raise PatchError("AppInfo 的 DLC 条目不是对象")
        dlc_id = str(entry.get("id") or "").strip()
        name = str(entry.get("name") or "").strip()
        if not _SANE_ID.fullmatch(dlc_id):
            raise PatchError(f"AppInfo 中的 DLC ID 非法：{entry.get('id')!r}")
        if not name or "\r" in name or "\n" in name:
            raise PatchError(f"AppInfo 中的 DLC 名称非法：{entry.get('name')!r}")
        if dlc_id in seen:
            continue
        seen.add(dlc_id)
        lines.append(f"{dlc_id} = {name}")
    return "\n".join(lines) + "\n"


def render_smoke_api_config(
    appinfo: Mapping[str, object],
    template: PatchTemplate,
) -> str:
    """Render ``SmokeAPI.config.json`` from an AppInfo document and template.

    SmokeAPI (v4.x) unlocks every DLC by default, so the generated config only
    pins the app status and mirrors the published DLC list into ``extra_dlcs``
    for store-less/pre-order DLCs that the public Steam database omits.
    """
    app_id = str(appinfo.get("app_id") or "").strip()
    if not _SANE_ID.fullmatch(app_id):
        raise PatchError("AppInfo missing a valid app_id")
    raw_dlcs = appinfo.get("dlcs")
    if not isinstance(raw_dlcs, (list, tuple)):
        raise PatchError("AppInfo missing a dlcs list")
    dlcs: dict[str, str] = {}
    for entry in raw_dlcs:
        if not isinstance(entry, Mapping):
            raise PatchError("AppInfo contains a non-object DLC entry")
        dlc_id = str(entry.get("id") or "").strip()
        name = str(entry.get("name") or "").strip()
        if not _SANE_ID.fullmatch(dlc_id):
            raise PatchError(f"AppInfo contains an invalid DLC ID: {dlc_id!r}")
        if not name or "\r" in name or "\n" in name:
            raise PatchError(f"AppInfo contains an invalid DLC name: {name!r}")
        dlcs.setdefault(dlc_id, name)
    config = {
        "$schema": (
            "https://raw.githubusercontent.com/acidicoala/SmokeAPI/refs/tags/"
            "v4.0.0/res/SmokeAPI.schema.json"
        ),
        "$version": 4,
        "logging": False,
        "log_steam_http": False,
        "default_app_status": "unlocked" if template.unlock_all else "original",
        "override_app_status": {},
        "override_dlc_status": {},
        "auto_inject_inventory": True,
        "extra_inventory_items": [],
        "extra_dlcs": {app_id: {"dlcs": dlcs}} if dlcs else {},
    }
    return json.dumps(config, ensure_ascii=False, indent=2) + "\n"


def render_patch_config(
    appinfo: Mapping[str, object],
    template: PatchTemplate,
) -> str:
    """Render the platform-specific unlock configuration for a template."""
    if template.config_format == PatchConfigFormat.SMOKEAPI_JSON:
        return render_smoke_api_config(appinfo, template)
    if template.config_format == PatchConfigFormat.CREAM_INI:
        return render_cream_api_ini(appinfo, template)
    raise PatchError(f"unsupported patch config format: {template.config_format}")


class PatchEngine:
    """Apply, audit, remove and repair a per-game CreamAPI-style patch.

    ``data_root`` is used as the parent for short-lived backup transactions.
    Callers should pass ``context.paths.data`` so backups live alongside the
    install engine's transaction logs.
    """

    def __init__(
        self,
        profile: PatchProfile,
        data_root: Path,
        *,
        replace: Callable[[Path, Path], None] = os.replace,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.profile = profile
        self.data_root = Path(data_root).resolve()
        self._replace = replace
        self._clock = clock

    # ---- persistent installation evidence ---------------------------------

    def _installation_identity(self, game_root: Path) -> str:
        identity = "|".join(
            (
                os.path.normcase(str(Path(game_root).resolve())),
                *(directory.casefold() for directory in self.profile.install_relative_dirs),
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @contextmanager
    def _installation_lock(self, game_root: Path):
        """Acquire a non-blocking cross-process lock for one installation."""
        lock_root = self.data_root / "patch-locks"
        lock_root.mkdir(parents=True, exist_ok=True)
        lock_path = lock_root / f"{self._installation_identity(game_root)}.lock"
        stream = lock_path.open("a+b")
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError) as error:
                raise PatchError(
                    "该游戏目录正在被另一个补丁操作占用，请等待其完成后重试"
                ) from error
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            stream.close()

    def _receipt_path(self, game_root: Path) -> Path:
        identity = "|".join(
            (
                str(Path(game_root).resolve()).casefold(),
                *(directory.casefold() for directory in self.profile.install_relative_dirs),
                self.profile.unlocker_dll_name.casefold(),
            )
        )
        key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return self.data_root / "patch-receipts" / f"{key}.json"

    @staticmethod
    def _sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _load_installation_record(self, game_root: Path) -> dict[str, object] | None:
        path = self._receipt_path(game_root)
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict) or value.get("schema") not in {1, 2, 3}:
            return None
        schema = int(value["schema"])
        expected_layout = {
            "install_relative_dir": self.profile.install_relative_dir,
            "unlocker_name": self.profile.unlocker_dll_name,
            ("backup_name" if schema == 1 else "runtime_original_name"):
                self.profile.runtime_original_library_name,
            "ini_name": self.profile.template.ini_target_name,
        }
        if any(value.get(key) != expected for key, expected in expected_layout.items()):
            return None
        if schema >= 3 and value.get("install_relative_dirs") != list(
            self.profile.install_relative_dirs
        ):
            return None
        runtime_hash = value.get(
            "backup_sha256" if schema == 1 else "runtime_original_sha256"
        )
        hashes = (value.get("unlocker_sha256"), runtime_hash, value.get("ini_sha256"))
        if any(
            not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item)
            for item in hashes
        ):
            return None
        normalized = dict(value)
        normalized["runtime_original_sha256"] = runtime_hash
        normalized["runtime_original_name"] = self.profile.runtime_original_library_name
        normalized["original_library_cache_key"] = str(
            value.get("original_library_cache_key") or ""
        )
        normalized["original_library_source"] = str(
            value.get("original_library_source")
            or value.get("backup_origin")
            or "legacy_receipt"
        )
        return normalized

    def _write_installation_record(
        self,
        game_root: Path,
        receipt: PatchReceipt,
        transaction_root: Path,
        actions: list[_Action],
    ) -> None:
        path = self._receipt_path(game_root)
        if path.is_file():
            self._backup_file(path, transaction_root, actions)
        document = {
            "schema": 3,
            "game_id": receipt.game_id,
            "game_root": str(Path(game_root).resolve()),
            "install_relative_dir": self.profile.install_relative_dir,
            "install_relative_dirs": list(self.profile.install_relative_dirs),
            "unlocker_name": self.profile.unlocker_dll_name,
            "runtime_original_name": self.profile.runtime_original_library_name,
            "ini_name": self.profile.template.ini_target_name,
            "unlocker_sha256": receipt.unlocker_sha256,
            "runtime_original_sha256": receipt.runtime_original_sha256,
            "ini_sha256": receipt.ini_sha256,
            "original_library_cache_key": receipt.original_library_cache_key,
            "original_library_source": receipt.original_library_source,
            "applied_at": self._clock(),
        }
        payload = json.dumps(
            document, ensure_ascii=False, indent=2, sort_keys=True
        ).encode("utf-8")
        self._write_file_atomic(payload, path, actions)

    def _delete_installation_record(self, game_root: Path) -> None:
        path = self._receipt_path(game_root)
        try:
            path.unlink(missing_ok=True)
            if path.parent.is_dir() and not any(path.parent.iterdir()):
                path.parent.rmdir()
        except OSError:
            pass

    def audit_recorded(self, game_root: Path) -> PatchAudit:
        """Verify an installed patch against its persisted content hashes."""
        game_root = Path(game_root)
        record = self._load_installation_record(game_root)
        if record is None:
            return PatchAudit(health=PatchHealth.UNKNOWN)
        expected = (
            (self.profile.unlocker_dll_name, str(record["unlocker_sha256"])),
            (self.profile.runtime_original_library_name, str(record["runtime_original_sha256"])),
            (self.profile.template.ini_target_name, str(record["ini_sha256"])),
        )
        missing: list[str] = []
        modified: list[str] = []
        matching: list[str] = []
        for directory, patch_root in zip(
            self.profile.install_relative_dirs, self._patch_roots(game_root)
        ):
            for filename, expected_hash in expected:
                path = patch_root / filename
                label = self._relative_file_path(directory, filename)
                if not path.is_file():
                    missing.append(label)
                    continue
                try:
                    actual_hash = self._sha256_file(path)
                except OSError:
                    modified.append(label)
                    continue
                if actual_hash == expected_hash:
                    matching.append(label)
                else:
                    modified.append(label)
        health = (
            PatchHealth.HEALTHY
            if not missing and not modified
            else PatchHealth.MODIFIED
        )
        return PatchAudit(
            health=health,
            missing=tuple(missing),
            modified=tuple(modified),
            matching=tuple(matching),
        )

    # ---- audit --------------------------------------------------------------

    def audit(
        self,
        game_root: Path,
        *,
        expected_unlocker_size: int,
        expected_backup_size: int,
    ) -> PatchAudit:
        """Compare the game directory to the sizes we would install."""
        game_root = Path(game_root)
        unlocker_name = self.profile.unlocker_dll_name
        backup_name = self.profile.runtime_original_library_name
        ini_name = self.profile.template.ini_target_name
        matching: list[str] = []
        modified: list[str] = []
        missing: list[str] = []
        root_states: list[tuple[bool, bool, bool, bool, bool]] = []
        for directory, patch_root in zip(
            self.profile.install_relative_dirs, self._patch_roots(game_root)
        ):
            unlocker = patch_root / unlocker_name
            backup = patch_root / backup_name
            ini = patch_root / ini_name
            unlocker_exists = unlocker.is_file()
            backup_exists = backup.is_file()
            ini_exists = ini.is_file()
            unlocker_matches = unlocker_exists and unlocker.stat().st_size == expected_unlocker_size
            backup_matches = backup_exists and backup.stat().st_size == expected_backup_size
            root_states.append((unlocker_exists, backup_exists, ini_exists, unlocker_matches, backup_matches))
            for path, label, exists, matches in (
                (unlocker, self._relative_file_path(directory, unlocker_name), unlocker_exists, unlocker_matches),
                (backup, self._relative_file_path(directory, backup_name), backup_exists, backup_matches),
            ):
                if not exists:
                    missing.append(label)
                elif matches:
                    matching.append(label)
                else:
                    modified.append(label)
            ini_label = self._relative_file_path(directory, ini_name)
            if ini_exists:
                matching.append(ini_label)
            else:
                missing.append(ini_label)
        if all(unlocker and backup and ini and unlocker_ok and backup_ok for unlocker, backup, ini, unlocker_ok, backup_ok in root_states):
            health = PatchHealth.HEALTHY
        elif all(not unlocker and not backup and not ini for unlocker, backup, ini, _unlocker_ok, _backup_ok in root_states):
            health = PatchHealth.ORIGINAL
        elif all(not backup and not ini and unlocker and not unlocker_ok for unlocker, backup, ini, unlocker_ok, _backup_ok in root_states):
            # Only a game-shipped DLL is present.
            health = PatchHealth.ORIGINAL
        else:
            health = PatchHealth.MODIFIED
        return PatchAudit(
            health=health,
            missing=tuple(missing),
            modified=tuple(modified),
            matching=tuple(matching),
        )

    # ---- apply --------------------------------------------------------------

    @_with_installation_lock
    def apply(
        self,
        game_root: Path,
        *,
        unlocker_dll_source: Path,
        appinfo_json_source: Path,
        game_id: str,
        original_dll_source: Path | None = None,
    ) -> PatchApplyResult:
        """Apply a complete publisher-provided patch transaction."""
        game_root = Path(game_root).resolve(strict=True)
        if not game_root.is_dir():
            raise PatchError("目标游戏目录不存在")
        unlocker_source = Path(unlocker_dll_source).resolve(strict=True)
        # New callers always provide the published original asset.  The
        # optional fallback only keeps pre-0.2 integrations callable while
        # they migrate; it is never used by the client workflow.
        original_source = (
            Path(original_dll_source).resolve(strict=True)
            if original_dll_source is not None
            else self._patch_root(game_root) / self.profile.unlocker_dll_name
        )
        appinfo_source = Path(appinfo_json_source).resolve(strict=True)
        self._reject_oversized_dll(unlocker_source, "补丁库")
        self._reject_oversized_dll(original_source, "原生库")
        unlocker_bytes = unlocker_source.read_bytes()
        original_bytes = original_source.read_bytes()
        if not _looks_like_binary(unlocker_bytes[:4096]):
            raise PatchError("补丁库二进制格式无效")
        if not _looks_like_binary(original_bytes[:4096]):
            raise PatchError("原生库二进制格式无效")
        unlocker_hash = self._sha256_bytes(unlocker_bytes)
        original_hash = self._sha256_bytes(original_bytes)
        unlocker_mode = unlocker_source.stat().st_mode & 0o777 if os.name != "nt" else None
        original_mode = original_source.stat().st_mode & 0o777 if os.name != "nt" else None
        appinfo = parse_appinfo_document(appinfo_source.read_bytes())
        config_body = render_patch_config(appinfo, self.profile.template)
        ini_payload = (
            _UTF8_BOM + config_body.encode("utf-8")
            if self.profile.template.config_format == PatchConfigFormat.CREAM_INI
            else config_body.encode("utf-8")
        )

        unlocker_name = self.profile.unlocker_dll_name
        runtime_name = self.profile.runtime_original_library_name
        ini_name = self.profile.template.ini_target_name
        audit_before = self.audit(
            game_root,
            expected_unlocker_size=len(unlocker_bytes),
            expected_backup_size=len(original_bytes),
        )
        actions: list[_Action] = []
        transaction_root = self._make_transaction_root("apply")
        replaced_paths: list[str] = []
        deleted_interference: list[str] = []
        runtime_changed = False
        unlocker_changed = False
        ini_written = False
        try:
            deleted_interference = self._delete_declared_interference_files(
                game_root, transaction_root, actions
            )
            patch_roots = self._patch_roots(game_root)
            for directory, patch_root in zip(
                self.profile.install_relative_dirs, patch_roots
            ):
                unlocker_path = patch_root / unlocker_name
                runtime_path = patch_root / runtime_name
                ini_path = patch_root / ini_name
                if not runtime_path.is_file() or self._sha256_file(runtime_path) != original_hash:
                    if runtime_path.is_file():
                        self._backup_file(runtime_path, transaction_root, actions)
                        replaced_paths.append(self._relative_file_path(directory, runtime_name))
                    self._write_file_atomic(
                        original_bytes, runtime_path, actions, mode=original_mode
                    )
                    runtime_changed = True
                if self._sha256_file(runtime_path) != original_hash:
                    raise PatchError("运行时原生库写入后校验失败")

                if not ini_path.is_file() or ini_path.read_bytes() != ini_payload:
                    if ini_path.is_file():
                        self._backup_file(ini_path, transaction_root, actions)
                        replaced_paths.append(self._relative_file_path(directory, ini_name))
                    self._write_file_atomic(ini_payload, ini_path, actions)
                    ini_written = True

                if not unlocker_path.is_file() or self._sha256_file(unlocker_path) != unlocker_hash:
                    if unlocker_path.is_file():
                        self._backup_file(unlocker_path, transaction_root, actions)
                        replaced_paths.append(self._relative_file_path(directory, unlocker_name))
                    self._write_file_atomic(
                        unlocker_bytes, unlocker_path, actions, mode=unlocker_mode
                    )
                    unlocker_changed = True

                if not unlocker_path.is_file():
                    raise PatchError("代理库写入后缺失，可能已被安全软件隔离")
                if self._sha256_file(unlocker_path) != unlocker_hash:
                    raise PatchError("代理库写入后校验失败")
                if (
                    not ini_path.is_file()
                    or self._sha256_file(ini_path) != self._sha256_bytes(ini_payload)
                ):
                    raise PatchError("补丁配置写入后校验失败")

            receipt = PatchReceipt(
                game_id=game_id,
                unlocker_dll_size=len(unlocker_bytes),
                runtime_original_library_size=len(original_bytes),
                ini_bytes=len(ini_payload),
                backup_created=runtime_changed,
                replaced_files=tuple(replaced_paths),
                unlocker_sha256=unlocker_hash,
                runtime_original_sha256=original_hash,
                ini_sha256=self._sha256_bytes(ini_payload),
                original_library_cache_key="",
                original_library_source="published_original",
            )
            self._write_installation_record(game_root, receipt, transaction_root, actions)
            audit_after = self.audit_recorded(game_root)
            if audit_after.health is not PatchHealth.HEALTHY:
                raise PatchError("补丁安装凭据校验失败，已回滚本次操作")
        except Exception:
            self._rollback(actions)
            self._cleanup_transaction(transaction_root)
            raise
        else:
            self._cleanup_transaction(transaction_root)

        return PatchApplyResult(
            receipt=receipt,
            audit_before=audit_before,
            audit_after=audit_after,
            unlocker_replaced=unlocker_changed,
            backup_created=runtime_changed,
            backup_replaced=runtime_changed
            and any(path.endswith(f"/{runtime_name}") or path == runtime_name for path in replaced_paths),
            ini_written=ini_written,
            interference_files_deleted=tuple(deleted_interference),
        )

    def repair_patch(self, game_root: Path, **sources) -> PatchApplyResult:
        """Idempotently repair managed files without clearing the game directory."""
        return self.apply(game_root, **sources)

    @_with_installation_lock
    def clean_interference_files(self, game_root: Path) -> tuple[str, ...]:
        """Delete configured stale files without rewriting an already healthy patch.

        This gives users of an older client the current cleanup behavior
        without an unnecessary patch download or replacement.
        """
        game_root = Path(game_root).resolve(strict=True)
        if not game_root.is_dir():
            raise PatchError("目标游戏目录不存在")
        actions: list[_Action] = []
        transaction_root = self._make_transaction_root("interference-cleanup")
        try:
            deleted = self._delete_declared_interference_files(
                game_root, transaction_root, actions
            )
        except Exception:
            self._rollback(actions)
            self._cleanup_transaction(transaction_root)
            raise
        else:
            self._cleanup_transaction(transaction_root)
            return tuple(deleted)

    # ---- remove -------------------------------------------------------------

    def _resolve_recorded_original(
        self,
        game_root: Path,
        record: dict[str, object],
    ) -> OriginalLibraryEntry:
        original_hash = str(record["runtime_original_sha256"])
        runtime_path = self._patch_root(game_root) / self.profile.runtime_original_library_name
        if runtime_path.is_file() and self._sha256_file(runtime_path) == original_hash:
            return OriginalLibraryEntry(
                installation_key="",
                sha256=original_hash,
                path=runtime_path,
                metadata_path=Path(),
                filename=self.profile.runtime_original_library_name,
                size_bytes=runtime_path.stat().st_size,
                binary_format="published",
                architecture="unknown",
                source="recorded_runtime_original",
            )
        raise PatchError("可信原生库缺失；请重新下载补丁资产后修复或移除")

    def inspect_original_restore(self, game_root: Path) -> PatchRestoreReadiness:
        """Preflight a fail-closed return to the original primary library."""
        game_root = Path(game_root).resolve(strict=True)
        patch_roots = self._patch_roots(game_root)
        managed_paths = tuple(
            (
                root / self.profile.unlocker_dll_name,
                root / self.profile.runtime_original_library_name,
                root / self.profile.template.ini_target_name,
            )
            for root in patch_roots
        )
        record_path = self._receipt_path(game_root)
        record = self._load_installation_record(game_root)
        patch_detected = record_path.is_file() or any(
            runtime.is_file() or ini.is_file() for _unlocker, runtime, ini in managed_paths
        )
        if record is None:
            if not patch_detected and all(unlocker.is_file() for unlocker, _runtime, _ini in managed_paths):
                return PatchRestoreReadiness(True, False, False)
            reason = (
                "补丁安装凭据缺失或损坏，无法证明主库和原生库来源；请通过游戏平台验证游戏文件"
                if patch_detected
                else "游戏主库缺失；请通过游戏平台验证游戏文件"
            )
            return PatchRestoreReadiness(
                False,
                patch_detected,
                any(runtime.is_file() for _unlocker, runtime, _ini in managed_paths),
                reason,
            )
        try:
            original = self._resolve_recorded_original(game_root, record)
        except (PatchError, OSError) as error:
            return PatchRestoreReadiness(False, True, False, str(error))
        for unlocker, _runtime, _ini in managed_paths:
            if not unlocker.is_file():
                return PatchRestoreReadiness(False, True, True, "游戏主库缺失，拒绝猜测恢复状态")
            try:
                if self._sha256_file(unlocker) != record["unlocker_sha256"]:
                    return PatchRestoreReadiness(False, True, True, "游戏主库已被外部修改，拒绝自动恢复")
            except OSError as error:
                return PatchRestoreReadiness(False, True, True, f"无法校验游戏主库：{error}")
        return PatchRestoreReadiness(True, True, original.path.is_file())

    @_with_installation_lock
    def remove(self, game_root: Path) -> tuple[str, ...]:
        """Restore the primary library first, then remove only verified managed files."""
        game_root = Path(game_root).resolve(strict=True)
        readiness = self.inspect_original_restore(game_root)
        if not readiness.patch_detected:
            if readiness.ready:
                return ()
            raise PatchError(readiness.reason)
        if not readiness.ready:
            raise PatchError(readiness.reason)
        record = self._load_installation_record(game_root)
        if record is None:
            raise PatchError("补丁安装凭据不可用，拒绝自动恢复")
        original = self._resolve_recorded_original(game_root, record)
        unlocker_name = self.profile.unlocker_dll_name
        runtime_name = self.profile.runtime_original_library_name
        ini_name = self.profile.template.ini_target_name
        target_paths = tuple(
            (directory, root / unlocker_name, root / runtime_name, root / ini_name)
            for directory, root in zip(
                self.profile.install_relative_dirs, self._patch_roots(game_root)
            )
        )
        if any(
            not unlocker.is_file()
            or self._sha256_file(unlocker) != str(record["unlocker_sha256"])
            for _directory, unlocker, _runtime, _ini in target_paths
        ):
            raise PatchError("代理库缺失或已被外部修改，拒绝自动恢复")

        actions: list[_Action] = []
        transaction_root = self._make_transaction_root("remove")
        touched: list[str] = []
        try:
            original_bytes = original.path.read_bytes()
            original_mode = original.path.stat().st_mode & 0o777 if os.name != "nt" else None
            for directory, unlocker, runtime, ini in target_paths:
                self._backup_file(unlocker, transaction_root, actions)
                self._write_file_atomic(original_bytes, unlocker, actions, mode=original_mode)
                if self._sha256_file(unlocker) != original.sha256:
                    raise PatchError("恢复主库后校验失败")
                touched.append(self._relative_file_path(directory, unlocker_name))

                for path, name, expected in (
                    (ini, ini_name, str(record["ini_sha256"])),
                    (runtime, runtime_name, str(record["runtime_original_sha256"])),
                ):
                    if path.is_file() and self._sha256_file(path) == expected:
                        self._backup_file(path, transaction_root, actions)
                        path.unlink()
                        actions.append(_DeletedFile(path, actions[-1].backup_path))
                        touched.append(self._relative_file_path(directory, name))
        except Exception:
            self._rollback(actions)
            self._cleanup_transaction(transaction_root)
            raise
        else:
            self._cleanup_transaction(transaction_root)
        self._delete_installation_record(game_root)
        return tuple(dict.fromkeys(touched))

    def restore_original(self, game_root: Path) -> tuple[str, ...]:
        """Compatibility name for the fail-closed original restore transaction."""
        return self.remove(game_root)

    # ---- internal helpers ---------------------------------------------------

    def _patch_root(self, game_root: Path) -> Path:
        return self._patch_roots(game_root)[0]

    def _patch_roots(self, game_root: Path) -> tuple[Path, ...]:
        try:
            return tuple(
                resolve_game_directory(
                    game_root,
                    directory,
                    field_name="patch install directory",
                    strict_root=True,
                )
                for directory in self.profile.install_relative_dirs
            )
        except (OSError, ValueError) as error:
            raise PatchError(str(error)) from error

    def _delete_declared_interference_files(
        self,
        game_root: Path,
        transaction_root: Path,
        actions: list[_Action],
    ) -> list[str]:
        """Preflight and transactionally remove stale files in every patch root."""
        patch_roots = self._patch_roots(game_root)
        managed_names = {name.casefold() for name in self.profile.patch_file_names}
        seen_targets: set[Path] = set()
        targets: list[tuple[Path, str]] = []
        for directory, patch_root in zip(
            self.profile.install_relative_dirs, patch_roots
        ):
            for relative in self.profile.interference_files:
                if relative.casefold() in managed_names:
                    raise PatchError(f"干扰文件列表不能包含受控补丁文件：{relative}")
                target = resolve_game_directory(
                    patch_root,
                    relative,
                    field_name="patch interference file",
                    strict_root=True,
                )
                if target in seen_targets:
                    continue
                seen_targets.add(target)
                display_path = self._relative_file_path(directory, relative)
                if target.is_symlink() or (target.exists() and not target.is_file()):
                    raise PatchError(
                        "干扰文件不是普通文件，拒绝清理：" + display_path
                    )
                if target.exists():
                    targets.append((target, display_path))

        deleted: list[str] = []
        for target, display_path in targets:
            self._backup_file(target, transaction_root, actions)
            target.unlink()
            actions.append(_DeletedFile(target, actions[-1].backup_path))
            deleted.append(display_path)
        return deleted

    @staticmethod
    def _relative_file_path(directory: str, filename: str) -> str:
        return filename if directory == "." else f"{directory}/{filename}"

    def _reject_oversized_dll(self, path: Path, label: str) -> None:
        size = path.stat().st_size
        if size <= 0:
            raise PatchError(f"{label} 大小为 0，无法应用")
        if size > MAX_PATCH_DLL_BYTES:
            raise PatchError(f"{label} 超过 {MAX_PATCH_DLL_BYTES // (1024 * 1024)} MiB，拒绝安装")

    def _make_transaction_root(self, operation: str) -> Path:
        # Random suffix guards against accidental reuse and gives us clean
        # per-operation cleanup semantics.
        transaction_id = f"{int(self._clock())}-{uuid.uuid4().hex[:8]}"
        root = self.data_root / "patch-transactions" / f"{operation}-{transaction_id}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _cleanup_transaction(self, transaction_root: Path) -> None:
        try:
            shutil.rmtree(transaction_root, ignore_errors=True)
            parent = transaction_root.parent
            if parent.is_dir() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            # Cleanup failures are informational only; the backups are safe
            # to delete manually and do not affect on-disk correctness.
            pass

    def _backup_file(
        self,
        path: Path,
        transaction_root: Path,
        actions: list[_Action],
    ) -> None:
        """Copy ``path`` into ``transaction_root`` so we can restore it later."""
        backup_path = transaction_root / f"{uuid.uuid4().hex}.{path.name}"
        # copy2 preserves mtime so the restored file looks unchanged to Steam.
        shutil.copy2(path, backup_path)
        actions.append(_BackedUpFile(path, backup_path))

    def _write_file_atomic(
        self,
        data: bytes,
        destination: Path,
        actions: list[_Action],
        *,
        mode: int | None = None,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        prior = destination.exists()
        # NamedTemporaryFile keeps us on the same filesystem so os.replace is
        # actually atomic and safe against half-written files.
        handle = tempfile.NamedTemporaryFile(
            "wb", delete=False, dir=str(destination.parent),
            suffix=".tmp", prefix=f".patch-{destination.name}-",
        )
        try:
            with handle as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                temporary = Path(stream.name)
            if mode is not None:
                os.chmod(temporary, mode)
            self._replace(temporary, destination)
        except Exception:
            try:
                Path(handle.name).unlink()
            except OSError:
                pass
            raise
        actions.append(_WroteFile(destination, existed_before=prior))

    def _move_atomic(
        self, source: Path, destination: Path, actions: list[_Action]
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_existed = destination.exists()
        self._replace(source, destination)
        actions.append(_MovedFile(source, destination, destination_existed))

    def _rollback(self, actions: Iterable[_Action]) -> None:
        # Iterate in reverse so the most recent side-effects are undone first;
        # a later action can only reference paths a previous one produced.
        for action in reversed(list(actions)):
            try:
                action.undo(self)
            except Exception:
                # Never let a rollback failure mask the original error.
                pass


# ---- internal action bookkeeping --------------------------------------------

@dataclass(frozen=True, slots=True)
class _Action:
    """Base for the internal undo log."""

    def undo(self, engine: "PatchEngine") -> None:  # pragma: no cover - interface only
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _BackedUpFile(_Action):
    original_path: Path
    backup_path: Path

    def undo(self, engine: "PatchEngine") -> None:
        if not self.backup_path.exists():
            return
        engine._replace(self.backup_path, self.original_path)


@dataclass(frozen=True, slots=True)
class _WroteFile(_Action):
    destination: Path
    existed_before: bool

    def undo(self, engine: "PatchEngine") -> None:
        if not self.existed_before and self.destination.exists():
            try:
                self.destination.unlink()
            except OSError:
                pass
        # If it existed before we started, a paired ``_BackedUpFile`` earlier
        # in the log will restore its previous contents.


@dataclass(frozen=True, slots=True)
class _MovedFile(_Action):
    source: Path
    destination: Path
    destination_existed_before: bool

    def undo(self, engine: "PatchEngine") -> None:
        if self.destination.exists() and not self.source.exists():
            engine._replace(self.destination, self.source)


@dataclass(frozen=True, slots=True)
class _DeletedFile(_Action):
    """Marker inserted after we hand-delete a file whose backup already exists."""

    deleted_path: Path
    backup_path: Path

    def undo(self, engine: "PatchEngine") -> None:  # pragma: no cover - trivial
        # Restoration is driven by the paired ``_BackedUpFile`` action.
        return


__all__ = [
    "MAX_APPINFO_BYTES",
    "MAX_PATCH_DLL_BYTES",
    "PatchApplyResult",
    "PatchEngine",
    "PatchError",
    "parse_appinfo_document",
    "render_cream_api_ini",
]
