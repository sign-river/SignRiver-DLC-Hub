"""Record when local DLC resources were last updated (no Steam comparison)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DlcFreshnessReport:
    """Snapshot of local package timestamps for publisher/client display."""

    resources_updated_at: str
    recorded_at: str
    package_count: int
    published_package_count: int
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "resources_updated_at": self.resources_updated_at,
            "recorded_at": self.recorded_at,
            "package_count": self.package_count,
            "published_package_count": self.published_package_count,
            "summary": self.summary,
        }

    def to_client_dict(self) -> dict[str, object]:
        """Compact payload embedded in the remote client cartridge document."""
        return {
            "resources_updated_at": self.resources_updated_at,
            "package_count": self.package_count,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "DlcFreshnessReport":
        stamp = str(
            value.get("resources_updated_at")
            or value.get("checked_at")
            or ""
        ).strip()
        recorded = str(value.get("recorded_at") or stamp).strip()
        package_count = int(
            value.get("package_count")
            or value.get("local_package_count")
            or 0
        )
        published = int(value.get("published_package_count") or 0)
        summary = str(value.get("summary") or "").strip()
        if not summary and stamp:
            summary = f"资源提交于 {stamp} · 本地 {package_count} 个包"
        elif not summary:
            summary = "尚未读取到本地资源时间"
        return cls(
            resources_updated_at=stamp,
            recorded_at=recorded,
            package_count=package_count,
            published_package_count=published,
            summary=summary,
        )


def build_resource_freshness(
    *,
    local_folders: tuple[Path, ...],
    published_paths: tuple[Path, ...] = (),
    published_package_count: int = 0,
) -> DlcFreshnessReport:
    """Derive a stamp from the newest local package / publish output mtime."""
    newest: float | None = None
    for path in (*local_folders, *published_paths):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    package_count = len(local_folders)
    recorded_at = _format_local(datetime.now(timezone.utc).astimezone())
    if newest is None:
        return DlcFreshnessReport(
            resources_updated_at="",
            recorded_at=recorded_at,
            package_count=package_count,
            published_package_count=published_package_count,
            summary=(
                f"本地尚未收录 DLC 包（发布输出 {published_package_count} 个）。"
                if package_count == 0
                else "无法读取本地资源修改时间。"
            ),
        )
    stamp = _format_local(datetime.fromtimestamp(newest).astimezone())
    summary = f"资源提交于 {stamp} · 本地 {package_count} 个包"
    if published_package_count:
        summary += f" · 发布输出 {published_package_count} 个"
    return DlcFreshnessReport(
        resources_updated_at=stamp,
        recorded_at=recorded_at,
        package_count=package_count,
        published_package_count=published_package_count,
        summary=summary,
    )


def save_freshness_report(path: Path, report: DlcFreshnessReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_freshness_report(path: Path) -> DlcFreshnessReport | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("freshness.json root must be an object")
    return DlcFreshnessReport.from_dict(payload)


def _format_local(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


__all__ = [
    "DlcFreshnessReport",
    "build_resource_freshness",
    "load_freshness_report",
    "save_freshness_report",
]
