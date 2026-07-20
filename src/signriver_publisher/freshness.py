"""Compare local cartridge DLC packages against Steam Store listings."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .cream import SteamAppInfo, SteamDlc
from .dlc_naming import parse_managed_folder


_NON_ALNUM = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class DlcFreshnessReport:
    """Result of comparing Steam's official DLC list with local packages."""

    status: str
    checked_at: str
    steam_app_id: str
    steam_game_name: str
    steam_dlc_count: int
    local_package_count: int
    published_package_count: int
    gap_count: int
    appinfo_update_time: str
    unmatched_steam_names: tuple[str, ...]
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "steam_app_id": self.steam_app_id,
            "steam_game_name": self.steam_game_name,
            "steam_dlc_count": self.steam_dlc_count,
            "local_package_count": self.local_package_count,
            "published_package_count": self.published_package_count,
            "gap_count": self.gap_count,
            "appinfo_update_time": self.appinfo_update_time,
            "unmatched_steam_names": list(self.unmatched_steam_names),
            "summary": self.summary,
        }

    def to_client_dict(self) -> dict[str, object]:
        """Compact payload embedded in the remote client cartridge document."""
        return {
            "status": self.status,
            "checked_at": self.checked_at,
            "steam_game_name": self.steam_game_name,
            "steam_dlc_count": self.steam_dlc_count,
            "package_count": self.local_package_count,
            "gap_count": self.gap_count,
            "appinfo_update_time": self.appinfo_update_time,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "DlcFreshnessReport":
        names = value.get("unmatched_steam_names")
        unmatched = tuple(str(item) for item in names) if isinstance(names, list) else ()
        return cls(
            status=str(value.get("status") or "unknown"),
            checked_at=str(value.get("checked_at") or ""),
            steam_app_id=str(value.get("steam_app_id") or ""),
            steam_game_name=str(value.get("steam_game_name") or ""),
            steam_dlc_count=int(value.get("steam_dlc_count") or 0),
            local_package_count=int(value.get("local_package_count") or 0),
            published_package_count=int(value.get("published_package_count") or 0),
            gap_count=int(value.get("gap_count") or 0),
            appinfo_update_time=str(value.get("appinfo_update_time") or ""),
            unmatched_steam_names=unmatched,
            summary=str(value.get("summary") or ""),
        )


def compare_steam_and_local(
    appinfo: SteamAppInfo,
    *,
    local_folders: tuple[Path, ...],
    published_package_count: int = 0,
) -> DlcFreshnessReport:
    local_slugs = tuple(
        parsed[1]
        for path in local_folders
        for parsed in [parse_managed_folder(path.name)]
        if parsed is not None
    )
    unmatched = tuple(
        dlc.name
        for dlc in appinfo.dlcs
        if not _matches_any_local(dlc, local_slugs)
    )
    steam_count = len(appinfo.dlcs)
    local_count = len(local_folders)
    gap = max(0, steam_count - local_count)
    if steam_count == 0 and local_count == 0:
        status = "unknown"
        summary = "Steam 与本地都没有 DLC 条目，无法判断。"
    elif gap == 0:
        status = "current"
        summary = (
            f"本地已收录 {local_count} 个 DLC 包，不少于 Steam 官方列表的 "
            f"{steam_count} 项，可视为最新。"
        )
    else:
        status = "behind"
        summary = (
            f"Steam 官方列表有 {steam_count} 项，本地卡带仅有 {local_count} 个包，"
            f"约落后 {gap} 项；请人工核对后导入缺失内容。"
        )
        if unmatched:
            summary += f" 名称未能匹配的 Steam DLC 示例：{', '.join(unmatched[:5])}"
            if len(unmatched) > 5:
                summary += f" 等共 {len(unmatched)} 项。"
    checked_at = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    return DlcFreshnessReport(
        status=status,
        checked_at=checked_at,
        steam_app_id=appinfo.app_id,
        steam_game_name=appinfo.name,
        steam_dlc_count=steam_count,
        local_package_count=local_count,
        published_package_count=published_package_count,
        gap_count=gap,
        appinfo_update_time=appinfo.update_time,
        unmatched_steam_names=unmatched[:40],
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


def _matches_any_local(dlc: SteamDlc, local_slugs: tuple[str, ...]) -> bool:
    steam_key = _normalize(dlc.name)
    if not steam_key:
        return False
    for slug in local_slugs:
        slug_key = _normalize(slug)
        if not slug_key:
            continue
        if slug_key in steam_key or steam_key in slug_key:
            return True
        if _token_overlap(slug, dlc.name):
            return True
    return False


def _normalize(value: str) -> str:
    return _NON_ALNUM.sub("", value.casefold())


def _token_overlap(slug: str, steam_name: str) -> bool:
    slug_tokens = {token for token in re.split(r"[_\-\s]+", slug.casefold()) if len(token) > 2}
    name_tokens = {
        token
        for token in re.split(r"[^a-z0-9]+", steam_name.casefold())
        if len(token) > 2
    }
    if not slug_tokens or not name_tokens:
        return False
    return len(slug_tokens & name_tokens) >= max(1, min(2, len(slug_tokens)))


__all__ = [
    "DlcFreshnessReport",
    "compare_steam_and_local",
    "load_freshness_report",
    "save_freshness_report",
]
