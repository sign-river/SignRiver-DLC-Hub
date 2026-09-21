"""Side-effect-free preflight checks for publisher release batches."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from .artifact_collector import ArtifactCollector
from .release_models import CheckResult, PreflightCheck, ReleaseKind, ReleasePlan, ReleaseStatus
from .updates import inspect_module_archive, inspect_update_package

_PROGRAM_REQUIRED_ROLES = frozenset({"windows_full", "steamos_full", "macos_full"})
_REMOTE_SOURCES = frozenset({"gitlink", "github"})
_PROGRAM_PLATFORM_BY_ROLE = {
    "windows_full": "windows",
    "steamos_full": "steamos",
    "macos_full": "macos",
}


def compute_input_fingerprint(plan: ReleasePlan) -> str:
    payload = {
        "kind": plan.kind.value,
        "target": plan.target,
        "artifacts": [artifact.fingerprint_payload() for artifact in sorted(plan.artifacts, key=lambda item: item.role)],
        "remote_targets": plan.remote_targets,
        "notes": plan.notes,
        "options": plan.options,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ReleasePreflightService:
    def run(self, plan: ReleasePlan) -> list[PreflightCheck]:
        fingerprint = compute_input_fingerprint(plan)
        if plan.input_fingerprint and plan.input_fingerprint != fingerprint:
            plan.confirmation.clear()
        checks = [
            self._check_artifact_paths(plan, fingerprint),
            self._check_frozen_fingerprints(plan, fingerprint),
            self._check_remote_targets(plan, fingerprint),
        ]
        if plan.kind is ReleaseKind.PROGRAM:
            checks.extend(self._program_checks(plan, fingerprint))
        elif plan.kind is ReleaseKind.GAME_CONTENT:
            checks.extend(self._game_content_checks(plan, fingerprint))
        elif plan.kind is ReleaseKind.HUB_ANNOUNCEMENT:
            checks.extend(self._hub_checks(plan, fingerprint))
        checks.append(self._check_acceptance(plan, fingerprint))
        checks.append(self._check_remote_filenames(plan, fingerprint))
        plan.preflight = checks
        plan.input_fingerprint = fingerprint
        target = (
            ReleaseStatus.PREFLIGHT_FAILED
            if any(check.hard_gate and check.result is CheckResult.FAIL for check in checks)
            else ReleaseStatus.AWAITING_CONFIRMATION
        )
        if plan.status is not target:
            if plan.status not in {ReleaseStatus.DRAFT, ReleaseStatus.PREFLIGHT_FAILED}:
                plan.invalidate_inputs("preflight rerun after editable inputs changed")
            plan.transition_to(target)
        return checks

    @staticmethod
    def is_current(plan: ReleasePlan) -> bool:
        return (
            bool(plan.input_fingerprint)
            and plan.input_fingerprint == compute_input_fingerprint(plan)
            and not any(
                artifact.required and ArtifactCollector.has_fingerprint_changed(artifact)
                for artifact in plan.artifacts
            )
        )

    @staticmethod
    def _check_acceptance(plan: ReleasePlan, fingerprint: str) -> PreflightCheck:
        snapshot = plan.options.get("acceptance_snapshot")
        result = snapshot.get("result") if isinstance(snapshot, dict) else None
        raw_results = result.get("results") if isinstance(result, dict) else None
        statuses = [
            str(item.get("status") or "")
            for item in raw_results.values()
            if isinstance(item, dict)
        ] if isinstance(raw_results, dict) else []
        passed = bool(statuses) and all(status == "passed" for status in statuses)
        counts = {status: statuses.count(status) for status in sorted(set(statuses))}
        return PreflightCheck(
            check_id="human.acceptance",
            category="acceptance",
            result=CheckResult.PASS if passed else CheckResult.WARNING,
            hard_gate=False,
            message=(
                f"人工验收快照通过（{len(statuses)} 项）。"
                if passed
                else "人工验收未完整通过；该结果仅供发布参考，不阻止确认。"
            ),
            remediation=None if passed else "可在验收中心补充验收快照，供后续复核参考。",
            evidence={"status_counts": counts, "snapshot_attached": isinstance(snapshot, dict)},
            input_fingerprint=fingerprint,
        )

    @staticmethod
    def _check_artifact_paths(plan: ReleasePlan, fingerprint: str) -> PreflightCheck:
        missing = [item.role for item in plan.artifacts if item.required and (not item.local_path or not Path(item.local_path).is_file())]
        return PreflightCheck(
            check_id="artifacts.local_paths",
            category="artifacts",
            result=CheckResult.FAIL if missing else CheckResult.PASS,
            hard_gate=True,
            message="必需产物路径完整。" if not missing else f"缺少必需产物：{', '.join(missing)}",
            remediation=None if not missing else "重新收集或替换缺失产物后再预检。",
            evidence={"missing_roles": missing},
            input_fingerprint=fingerprint,
        )

    @staticmethod
    def _check_frozen_fingerprints(plan: ReleasePlan, fingerprint: str) -> PreflightCheck:
        changed = [item.role for item in plan.artifacts if item.required and ArtifactCollector.has_fingerprint_changed(item)]
        return PreflightCheck(
            check_id="artifacts.fingerprints",
            category="artifacts",
            result=CheckResult.FAIL if changed else CheckResult.PASS,
            hard_gate=True,
            message="冻结指纹有效。" if not changed else f"产物已变化：{', '.join(changed)}",
            remediation=None if not changed else "重新收集产物并生成新的预检快照。",
            evidence={"changed_roles": changed},
            input_fingerprint=fingerprint,
        )

    @staticmethod
    def _check_remote_targets(plan: ReleasePlan, fingerprint: str) -> PreflightCheck:
        configured = sorted(name for name, config in plan.remote_targets.items() if config)
        passed = set(configured) == _REMOTE_SOURCES
        return PreflightCheck(
            check_id="remote.dual_source",
            category="remote",
            result=CheckResult.PASS if passed else CheckResult.FAIL,
            hard_gate=True,
            message="GitLink 与 GitHub 双源目标已配置。" if passed else "发布目标必须且只能包含 GitLink 与 GitHub。",
            remediation=None if passed else "配置 GitLink 与 GitHub 的非敏感目标摘要。",
            evidence={"configured_sources": configured},
            input_fingerprint=fingerprint,
        )

    @staticmethod
    def _check_remote_filenames(plan: ReleasePlan, fingerprint: str) -> PreflightCheck:
        grouped: dict[str, list[str]] = {}
        for artifact in plan.artifacts:
            grouped.setdefault(artifact.filename.casefold(), []).append(artifact.role)
        duplicates = {name: roles for name, roles in grouped.items() if len(roles) > 1}
        return PreflightCheck(
            check_id="artifacts.remote_names",
            category="artifacts",
            result=CheckResult.FAIL if duplicates else CheckResult.PASS,
            hard_gate=True,
            message="远端文件名无冲突。" if not duplicates else "存在重复的远端文件名。",
            remediation=None if not duplicates else "重命名冲突附件后重新创建批次。",
            evidence={"duplicates": duplicates},
            input_fingerprint=fingerprint,
        )

    def _program_checks(self, plan: ReleasePlan, fingerprint: str) -> Iterable[PreflightCheck]:
        roles = {item.role for item in plan.artifacts}
        missing = sorted(_PROGRAM_REQUIRED_ROLES - roles)
        target_version = str(plan.target.get("version", "")).strip()
        # 只有本次发布必须使用的产物才参与版本一致性判断；模块归档目录里的历史
        # 版本会被一并同步到 modules Release，它们的版本号本来就不等于目标版本。
        inconsistent = sorted({
            item.version
            for item in plan.artifacts
            if item.required and item.version and item.version != target_version
        })
        module_archives = [item for item in plan.artifacts if item.role == "module_archive"]
        return (
            PreflightCheck(
                check_id="program.platform_packages",
                category="program",
                result=CheckResult.FAIL if missing else CheckResult.PASS,
                hard_gate=True,
                message="三端程序包齐全。" if not missing else f"缺少平台包：{', '.join(missing)}",
                remediation=None if not missing else "在对应原生平台完成构建并汇总到收件目录。",
                evidence={"missing_roles": missing},
                input_fingerprint=fingerprint,
            ),
            self._check_program_package_structure(plan, fingerprint, target_version),
            self._check_program_module_archives(module_archives, fingerprint, target_version),
            PreflightCheck(
                check_id="program.version_consistency",
                category="program",
                result=CheckResult.FAIL if not target_version or inconsistent else CheckResult.PASS,
                hard_gate=True,
                message="目标版本与产物版本一致。" if target_version and not inconsistent else "目标版本为空或产物版本不一致。",
                remediation=None if target_version and not inconsistent else "统一三端版本号后重新收集。",
                evidence={"target_version": target_version, "inconsistent_versions": inconsistent},
                input_fingerprint=fingerprint,
            ),
            PreflightCheck(
                check_id="program.release_notes",
                category="program",
                result=CheckResult.PASS if plan.notes.strip() else CheckResult.FAIL,
                hard_gate=True,
                message="更新说明已填写。" if plan.notes.strip() else "更新说明为空。",
                remediation=None if plan.notes.strip() else "填写面向用户的中文更新说明。",
                input_fingerprint=fingerprint,
            ),
        )

    @staticmethod
    def _check_program_module_archives(
        artifacts, fingerprint: str, target_version: str
    ) -> PreflightCheck:
        errors: dict[str, str] = {}
        matched_target = False
        extra_versions: list[str] = []
        for artifact in artifacts:
            try:
                info = inspect_module_archive(Path(artifact.local_path))
            except (OSError, ValueError) as error:
                errors[artifact.filename] = str(error)
                continue
            if info.version == target_version:
                matched_target = True
            else:
                # 模块归档目录里的历史版本会一并同步到 modules Release，
                # 用于让云端与仓库基线保持一致，因此不算错误。
                extra_versions.append(info.version)
        if not matched_target:
            errors["module_archive"] = (
                f"未找到与当前版本匹配的模块归档（期望 {target_version}）"
            )
        return PreflightCheck(
            check_id="program.module_archives",
            category="program",
            result=CheckResult.FAIL if errors else CheckResult.PASS,
            hard_gate=True,
            message=(
                (
                    f"模块归档已就绪（{len(artifacts)} 个"
                    + (
                        f"，其中历史版本 {len(extra_versions)} 个会一并同步"
                        if extra_versions
                        else ""
                    )
                    + "）。"
                )
                if not errors
                else "模块归档缺失、损坏或版本不匹配。"
            ),
            remediation=(
                None
                if not errors
                else "在模块归档目录放入当前版本的 SignRiver-DLC-Hub-module-v<版本>.zip 后重新验证。"
            ),
            evidence={
                "archive_count": len(artifacts),
                "extra_versions": sorted(extra_versions),
                "errors": errors,
            },
            input_fingerprint=fingerprint,
        )
    @staticmethod
    def _check_program_package_structure(
        plan: ReleasePlan, fingerprint: str, target_version: str
    ) -> PreflightCheck:
        errors: dict[str, str] = {}
        for artifact in plan.artifacts:
            expected_platform = _PROGRAM_PLATFORM_BY_ROLE.get(artifact.role)
            if expected_platform is None:
                continue
            try:
                info = inspect_update_package(Path(artifact.local_path))
            except (OSError, ValueError) as error:
                errors[artifact.role] = str(error)
                continue
            expected = ("full", target_version, expected_platform, "x64")
            actual = (
                info.kind,
                info.version,
                info.target_platform,
                info.target_arch,
            )
            if actual != expected:
                errors[artifact.role] = (
                    "包内元数据不匹配："
                    f"期望 {expected[0]} {expected[1]} {expected[2]}-{expected[3]}，"
                    f"实际 {actual[0]} {actual[1]} {actual[2]}-{actual[3]}"
                )
        return PreflightCheck(
            check_id="program.package_structure",
            category="program",
            result=CheckResult.FAIL if errors else CheckResult.PASS,
            hard_gate=True,
            message="三端程序包结构与内嵌平台元数据正确。" if not errors else "程序包结构或内嵌平台元数据异常。",
            remediation=None if not errors else "在对应原生平台重新构建异常包并重新收集。",
            evidence={"errors": errors},
            input_fingerprint=fingerprint,
        )

    @staticmethod
    def _game_content_checks(plan: ReleasePlan, fingerprint: str) -> Iterable[PreflightCheck]:
        roles = [item.role for item in plan.artifacts]
        game_id = str(plan.target.get("game_id") or "").strip()
        release_tag = str(plan.target.get("release_tag") or "").strip()
        catalog_count = roles.count("catalog")
        attachment_count = roles.count("content_attachment")
        target_ok = bool(game_id and release_tag)
        structure_ok = catalog_count == 1 and attachment_count >= 1
        return (
            PreflightCheck(
                check_id="content.target",
                category="content",
                result=CheckResult.PASS if target_ok else CheckResult.FAIL,
                hard_gate=True,
                message="游戏与 Release 目标完整。" if target_ok else "游戏 ID 或 Release 标签为空。",
                remediation=None if target_ok else "补齐游戏 ID 与 Release 标签。",
                evidence={"game_id": game_id, "release_tag": release_tag},
                input_fingerprint=fingerprint,
            ),
            PreflightCheck(
                check_id="content.snapshot_structure",
                category="content",
                result=CheckResult.PASS if structure_ok else CheckResult.FAIL,
                hard_gate=True,
                message="内容附件与唯一目录索引齐全。" if structure_ok else "内容发布必须包含至少一个附件和且仅一个 catalog。",
                remediation=None if structure_ok else "重新选择内容附件与 catalog.json。",
                evidence={"attachment_count": attachment_count, "catalog_count": catalog_count},
                input_fingerprint=fingerprint,
            ),
        )

    @staticmethod
    def _hub_checks(plan: ReleasePlan, fingerprint: str) -> Iterable[PreflightCheck]:
        roles = [item.role for item in plan.artifacts]
        index_count = roles.count("hub_index")
        snapshot_count = roles.count("hub_snapshot")
        structure_ok = index_count == 1 and snapshot_count >= 1
        return (
            PreflightCheck(
                check_id="hub.snapshot_structure",
                category="hub",
                result=CheckResult.PASS if structure_ok else CheckResult.FAIL,
                hard_gate=True,
                message="Hub 快照与唯一主索引齐全。" if structure_ok else "Hub 发布必须包含至少一个快照和且仅一个主索引。",
                remediation=None if structure_ok else "重新选择 Hub 快照与主索引。",
                evidence={"snapshot_count": snapshot_count, "index_count": index_count},
                input_fingerprint=fingerprint,
            ),
        )
