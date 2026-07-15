"""Crash-safe, idempotent CreamAPI-style patch installer.

The engine performs three related operations for a single game root:

* ``apply``    — install the patch DLL and render ``cream_api.ini`` from the
  published Steam AppInfo JSON, keeping any pre-existing original DLL as
  ``steam_api64_o.dll`` and refusing to overwrite that backup with a patched
  DLL.  Repeated runs are idempotent when the on-disk sizes already match
  the bundle we would install.
* ``remove``   — undo an apply: delete the patch DLL and the ini file, then
  rename ``steam_api64_o.dll`` back to ``steam_api64.dll`` so the game boots
  against its untouched original.
* ``reset``    — wipe all three patch files without restoring anything.
  This is what "一键修复" uses right before it re-downloads the assets and
  applies them again.

All writes go through ``write-temp + os.replace`` so a crash halfway leaves
either the pre-change file or the fully written new file in place.  Backups
of files we are about to destroy are stored under a per-transaction folder
inside the shared ``data`` root; successful operations delete their backup
folder while errors trigger an in-memory rollback that restores it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ...domain.patches import (
    PatchAudit,
    PatchHealth,
    PatchProfile,
    PatchReceipt,
    PatchTemplate,
)
from ...domain.paths import resolve_game_directory


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


@dataclass(frozen=True, slots=True)
class PatchRestoreReadiness:
    """Whether the current patch layout can be restored without guessing."""

    ready: bool
    patch_detected: bool
    backup_available: bool
    reason: str = ""


def _ini_bool(value: bool) -> str:
    return "True" if value else "False"


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
        patch_root = self._patch_root(game_root)
        unlocker_name = self.profile.unlocker_dll_name
        backup_name = self.profile.original_backup_dll_name
        ini_name = self.profile.template.ini_target_name
        unlocker = patch_root / unlocker_name
        backup = patch_root / backup_name
        ini = patch_root / ini_name
        unlocker_label = self.profile.relative_file_path(unlocker_name)
        backup_label = self.profile.relative_file_path(backup_name)
        ini_label = self.profile.relative_file_path(ini_name)
        matching: list[str] = []
        modified: list[str] = []
        missing: list[str] = []
        unlocker_exists = unlocker.is_file()
        backup_exists = backup.is_file()
        ini_exists = ini.is_file()
        if unlocker_exists:
            if unlocker.stat().st_size == expected_unlocker_size:
                matching.append(unlocker_label)
            else:
                modified.append(unlocker_label)
        else:
            missing.append(unlocker_label)
        if backup_exists:
            if backup.stat().st_size == expected_backup_size:
                matching.append(backup_label)
            else:
                modified.append(backup_label)
        else:
            missing.append(backup_label)
        if ini_exists:
            matching.append(ini_label)
        else:
            missing.append(ini_label)
        if (
            unlocker_exists
            and backup_exists
            and ini_exists
            and unlocker.stat().st_size == expected_unlocker_size
            and backup.stat().st_size == expected_backup_size
        ):
            health = PatchHealth.HEALTHY
        elif not unlocker_exists and not backup_exists and not ini_exists:
            health = PatchHealth.ORIGINAL
        elif (
            not backup_exists
            and not ini_exists
            and unlocker_exists
            and unlocker.stat().st_size != expected_unlocker_size
        ):
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

    def apply(
        self,
        game_root: Path,
        *,
        unlocker_dll_source: Path,
        original_backup_dll_source: Path,
        appinfo_json_source: Path,
        game_id: str,
    ) -> PatchApplyResult:
        """Install the patch DLL, keep a genuine original backup and render ini."""
        game_root = Path(game_root).resolve(strict=True)
        if not game_root.is_dir():
            raise PatchError("目标游戏目录不存在")
        unlocker_source = Path(unlocker_dll_source).resolve(strict=True)
        backup_source = Path(original_backup_dll_source).resolve(strict=True)
        appinfo_source = Path(appinfo_json_source).resolve(strict=True)

        self._reject_oversized_dll(unlocker_source, "补丁 DLL")
        self._reject_oversized_dll(backup_source, "原版备份 DLL")
        appinfo_bytes = appinfo_source.read_bytes()
        appinfo = parse_appinfo_document(appinfo_bytes)
        ini_body = render_cream_api_ini(appinfo, self.profile.template)
        ini_payload = _UTF8_BOM + ini_body.encode("utf-8")

        our_unlocker_size = unlocker_source.stat().st_size
        our_backup_size = backup_source.stat().st_size

        audit_before = self.audit(
            game_root,
            expected_unlocker_size=our_unlocker_size,
            expected_backup_size=our_backup_size,
        )

        unlocker_name = self.profile.unlocker_dll_name
        backup_name = self.profile.original_backup_dll_name
        ini_name = self.profile.template.ini_target_name
        patch_root = self._patch_root(game_root)
        unlocker_path = patch_root / unlocker_name
        backup_path = patch_root / backup_name
        ini_path = patch_root / ini_name

        actions: list[_Action] = []
        transaction_root = self._make_transaction_root("apply")

        try:
            game_unlocker_size = (
                unlocker_path.stat().st_size if unlocker_path.is_file() else None
            )
            game_backup_size = (
                backup_path.stat().st_size if backup_path.is_file() else None
            )

            backup_created = False
            backup_replaced = False
            unlocker_replaced = False
            replaced_paths: list[str] = []

            # ----- ensure the original backup exists and matches ours -------
            if not backup_path.is_file():
                # No backup yet.  If the on-disk unlocker looks like an untouched
                # game DLL (different size from our patch), promote it to the
                # backup before we drop our patched DLL in place.
                if unlocker_path.is_file() and game_unlocker_size != our_unlocker_size:
                    self._backup_file(unlocker_path, transaction_root, actions)
                    self._move_atomic(unlocker_path, backup_path, actions)
                    backup_created = True
                    # Now the unlocker slot is empty, so we always write ours below.
                    unlocker_replaced = True
                else:
                    # Either there is no unlocker at all, or the existing one is
                    # already our patch (its backup was previously removed by
                    # some cleanup).  Drop our packaged backup DLL in place.
                    self._write_file_atomic(
                        backup_source.read_bytes(), backup_path, actions
                    )
                    backup_created = True
            else:
                # A backup already exists.  If its size matches our packaged
                # backup DLL, we treat it as trustworthy and leave it alone.
                if game_backup_size != our_backup_size:
                    # The existing "backup" is not ours; back it up first, then
                    # replace with our known-good copy so removal later can
                    # restore a working original.
                    self._backup_file(backup_path, transaction_root, actions)
                    self._write_file_atomic(
                        backup_source.read_bytes(), backup_path, actions
                    )
                    backup_replaced = True
                    replaced_paths.append(self.profile.relative_file_path(backup_name))

            # ----- install the patch DLL ------------------------------------
            if not unlocker_path.is_file():
                self._write_file_atomic(
                    unlocker_source.read_bytes(), unlocker_path, actions
                )
                unlocker_replaced = True
            elif unlocker_path.stat().st_size != our_unlocker_size:
                self._backup_file(unlocker_path, transaction_root, actions)
                self._write_file_atomic(
                    unlocker_source.read_bytes(), unlocker_path, actions
                )
                unlocker_replaced = True
                replaced_paths.append(self.profile.relative_file_path(unlocker_name))
            else:
                # Size already matches; skip rewriting to keep the operation
                # idempotent even on filesystems with poor write endurance.
                pass

            # ----- write cream_api.ini --------------------------------------
            ini_written = False
            if ini_path.is_file():
                existing = ini_path.read_bytes()
                if existing != ini_payload:
                    self._backup_file(ini_path, transaction_root, actions)
                    self._write_file_atomic(ini_payload, ini_path, actions)
                    ini_written = True
                    replaced_paths.append(self.profile.relative_file_path(ini_name))
            else:
                self._write_file_atomic(ini_payload, ini_path, actions)
                ini_written = True

            receipt = PatchReceipt(
                game_id=game_id,
                unlocker_dll_size=our_unlocker_size,
                original_backup_dll_size=our_backup_size,
                ini_bytes=len(ini_payload),
                backup_created=backup_created or backup_replaced,
                replaced_files=tuple(replaced_paths),
            )

            # Security software can remove or quarantine a DLL immediately
            # after the atomic rename succeeds.  Treat the write as committed
            # only after all required files can still be observed on disk.
            # The backup DLL is intentionally checked for presence only: when
            # a vanilla game DLL is promoted to the backup slot its size may
            # legitimately differ from the packaged fallback DLL.
            if not unlocker_path.is_file():
                raise PatchError(
                    f"补丁写入后 {unlocker_name} 消失；文件可能被安全软件隔离"
                )
            if unlocker_path.stat().st_size != our_unlocker_size:
                raise PatchError(
                    f"补丁写入后 {unlocker_name} 大小异常；文件可能被安全软件修改或拦截"
                )
            if not backup_path.is_file():
                raise PatchError(
                    f"补丁写入后 {backup_name} 消失；文件可能被安全软件隔离"
                )
            if not ini_path.is_file() or ini_path.read_bytes() != ini_payload:
                raise PatchError(
                    f"补丁写入后 {ini_name} 缺失或内容不完整；文件可能被安全软件拦截"
                )

            audit_after = self.audit(
                game_root,
                expected_unlocker_size=our_unlocker_size,
                expected_backup_size=our_backup_size,
            )
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
            unlocker_replaced=unlocker_replaced,
            backup_created=backup_created,
            backup_replaced=backup_replaced,
            ini_written=ini_written,
        )

    # ---- remove -------------------------------------------------------------

    def inspect_original_restore(self, game_root: Path) -> PatchRestoreReadiness:
        """Preflight a safe return to the game's original loader DLL."""
        game_root = Path(game_root).resolve(strict=True)
        patch_root = self._patch_root(game_root)
        unlocker = patch_root / self.profile.unlocker_dll_name
        backup = patch_root / self.profile.original_backup_dll_name
        ini = patch_root / self.profile.template.ini_target_name
        if backup.is_file():
            try:
                size = backup.stat().st_size
            except OSError as error:
                return PatchRestoreReadiness(
                    False, True, True, f"无法读取原版 DLL 备份：{error}"
                )
            if size <= 0 or size > MAX_PATCH_DLL_BYTES:
                return PatchRestoreReadiness(
                    False, True, True, "原版 DLL 备份大小异常，拒绝自动恢复"
                )
            return PatchRestoreReadiness(True, True, True)
        if ini.is_file():
            return PatchRestoreReadiness(
                False,
                True,
                False,
                "检测到补丁配置，但原版 DLL 备份缺失；请先通过游戏平台验证游戏文件",
            )
        if unlocker.is_file():
            return PatchRestoreReadiness(True, False, False)
        return PatchRestoreReadiness(
            False,
            False,
            False,
            "原版 DLL 与备份均不存在；请先通过游戏平台验证游戏文件",
        )

    def restore_original(self, game_root: Path) -> tuple[str, ...]:
        """Undo our patch only when an original loader can be proven present."""
        readiness = self.inspect_original_restore(game_root)
        if not readiness.ready:
            raise PatchError(readiness.reason)
        if not readiness.patch_detected:
            return ()
        return self.remove(game_root)

    def remove(self, game_root: Path) -> tuple[str, ...]:
        """Delete patch files and restore the original DLL, if we have a backup.

        Returns the list of files that were removed or restored so the UI can
        report the exact operation to the user.
        """
        game_root = Path(game_root).resolve(strict=True)
        unlocker_name = self.profile.unlocker_dll_name
        backup_name = self.profile.original_backup_dll_name
        ini_name = self.profile.template.ini_target_name
        patch_root = self._patch_root(game_root)
        unlocker = patch_root / unlocker_name
        backup = patch_root / backup_name
        ini = patch_root / ini_name

        actions: list[_Action] = []
        transaction_root = self._make_transaction_root("remove")
        touched: list[str] = []
        try:
            if ini.is_file():
                self._backup_file(ini, transaction_root, actions)
                ini.unlink()
                actions.append(_DeletedFile(ini, actions[-1].backup_path))  # noqa: E501 - see below
                touched.append(self.profile.relative_file_path(ini_name))
            if backup.is_file():
                # Restoring the backup as the primary DLL is the safest recovery
                # path: even if our patch DLL has been altered by something else,
                # the game will boot again against a legitimate original.
                if unlocker.is_file():
                    self._backup_file(unlocker, transaction_root, actions)
                    unlocker.unlink()
                    touched.append(self.profile.relative_file_path(unlocker_name))
                self._backup_file(backup, transaction_root, actions)
                self._move_atomic(backup, unlocker, actions)
                touched.append(self.profile.relative_file_path(backup_name))
            elif unlocker.is_file():
                self._backup_file(unlocker, transaction_root, actions)
                unlocker.unlink()
                touched.append(self.profile.relative_file_path(unlocker_name))
        except Exception:
            self._rollback(actions)
            self._cleanup_transaction(transaction_root)
            raise
        else:
            self._cleanup_transaction(transaction_root)
        # De-dup while preserving order for a nicer UI message.
        seen: set[str] = set()
        ordered: list[str] = []
        for name in touched:
            if name not in seen:
                seen.add(name)
                ordered.append(name)
        return tuple(ordered)

    # ---- reset (used by "一键修复") ----------------------------------------

    def reset(self, game_root: Path) -> tuple[str, ...]:
        """Delete every patch file without restoring the game DLL.

        The caller (``一键修复``) will immediately re-download and re-apply
        the patch, so we want to start from a known-empty slate; keeping the
        original around would only complicate the re-apply path.
        """
        game_root = Path(game_root).resolve(strict=True)
        removed: list[str] = []
        transaction_root = self._make_transaction_root("reset")
        actions: list[_Action] = []
        try:
            patch_root = self._patch_root(game_root)
            for name in self.profile.patch_file_names:
                path = patch_root / name
                if path.is_file():
                    self._backup_file(path, transaction_root, actions)
                    path.unlink()
                    removed.append(self.profile.relative_file_path(name))
        except Exception:
            self._rollback(actions)
            self._cleanup_transaction(transaction_root)
            raise
        else:
            self._cleanup_transaction(transaction_root)
        return tuple(removed)

    # ---- internal helpers ---------------------------------------------------

    def _patch_root(self, game_root: Path) -> Path:
        try:
            return resolve_game_directory(
                game_root,
                self.profile.install_relative_dir,
                field_name="patch install directory",
                strict_root=True,
            )
        except (OSError, ValueError) as error:
            raise PatchError(str(error)) from error

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
        self, data: bytes, destination: Path, actions: list[_Action]
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
