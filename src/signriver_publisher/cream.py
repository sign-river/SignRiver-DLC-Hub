from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class AppInfoError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SteamDlc:
    app_id: str
    name: str


@dataclass(frozen=True, slots=True)
class SteamAppInfo:
    app_id: str
    name: str
    update_time: str
    dlcs: tuple[SteamDlc, ...]


def load_steam_appinfo(path: Path, *, expected_app_id: str = "") -> SteamAppInfo:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AppInfoError(f"无法读取 Steam AppInfo：{error}") from error
    if not isinstance(value, dict):
        raise AppInfoError("Steam AppInfo 顶层必须是对象")
    app_id = _numeric_id(value.get("app_id"), "app_id")
    if expected_app_id and app_id != expected_app_id:
        raise AppInfoError(f"Steam AppInfo 的 app_id 是 {app_id}，当前游戏要求 {expected_app_id}")
    name = _text(value.get("name"), "name")
    update_time = str(value.get("update_time", "")).strip()
    raw_dlcs = value.get("dlcs")
    if not isinstance(raw_dlcs, list):
        raise AppInfoError("Steam AppInfo 缺少 dlcs 数组")
    dlcs: list[SteamDlc] = []
    seen: set[str] = set()
    for index, item in enumerate(raw_dlcs, start=1):
        if not isinstance(item, dict):
            raise AppInfoError(f"第 {index} 个 DLC 不是对象")
        dlc_id = _numeric_id(item.get("id"), f"dlcs[{index}].id")
        if dlc_id in seen:
            raise AppInfoError(f"Steam AppInfo 包含重复 DLC ID：{dlc_id}")
        seen.add(dlc_id)
        dlcs.append(SteamDlc(dlc_id, _text(item.get("name"), f"dlcs[{index}].name")))
    return SteamAppInfo(app_id, name, update_time, tuple(dlcs))


def generate_cream_api_ini(
    appinfo: SteamAppInfo,
    *,
    language: str = "schinese",
    unlock_all: bool = True,
    extra_protection: bool = False,
    force_offline: bool = False,
) -> str:
    language = language.strip()
    if not language or any(character in language for character in "\r\n="):
        raise ValueError("invalid CreamAPI language")
    lines = [
        "[steam]",
        f"appid = {appinfo.app_id}",
        f"language = {language}",
        f"unlockall = {_ini_bool(unlock_all)}",
        f"extraprotection = {_ini_bool(extra_protection)}",
        f"forceoffline = {_ini_bool(force_offline)}",
        "",
        "[dlc]",
    ]
    lines.extend(f"{item.app_id} = {item.name}" for item in appinfo.dlcs)
    return "\n".join(lines) + "\n"


def _numeric_id(value: object, field: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text.isdigit():
        raise AppInfoError(f"{field} 必须是数字 ID")
    return text


def _text(value: object, field: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text or "\r" in text or "\n" in text:
        raise AppInfoError(f"{field} 不能为空或包含换行")
    return text


def _ini_bool(value: bool) -> str:
    return "True" if value else "False"
