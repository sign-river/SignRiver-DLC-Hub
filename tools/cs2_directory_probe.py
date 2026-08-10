"""Probe a Cities: Skylines II installation and produce a directory report.

The report helps the maintainer determine:
- the game root directory
- DLC content folders under ``Cities2_Data\\Content``
- where ``Cities2.exe`` and ``steam_api64.dll`` live

Game-directory auto-detection mirrors the main app: it reads the Windows
Steam registry/install locations, parses ``libraryfolders.vdf`` and locates
the game through ``appmanifest_<appid>.acf`` (AppID 949230), with a
folder-name fallback and a manual path input as last resort.

The script is deliberately dependency-free (stdlib only) so it can be sent
to a friend who may not have any Python packages installed.

Usage:
    python cs2_directory_probe.py            # auto-locate + interactive
    python cs2_directory_probe.py --path "D:\\SteamLibrary\\steamapps\\common\\Cities Skylines II"
    python cs2_directory_probe.py --out C:\\temp
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import winreg
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CS2_APPID = "949230"
GAME_FOLDER_CANDIDATES = (
    "Cities Skylines II",
    "Cities Skylines 2",
    "Cities Skylines II - Cities2",
)
OUTPUT_PREFIX = "CS2目录探测报告"

MAX_VDF_BYTES = 4 * 1024 * 1024
MAX_VDF_DEPTH = 64


def _utf8_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        os.system("chcp 65001 >nul")
    except Exception:
        pass

def _default_out_dir() -> Path:
    """Report output directory: EXE folder when frozen, else script folder."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent
    try:
        probe = base / ".probe_write_check"
        probe.write_text("x", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return base
    except OSError:
        return Path.home() / "Desktop"


def _pause_exit(code: int) -> int:
    print("")
    print("按回车键关闭窗口。")
    _safe_input("")
    return code


# ---------------------------------------------------------------------------
# Steam VDF / library discovery (mirrors app adapters/common/steam.py)
# ---------------------------------------------------------------------------

class VdfError(ValueError):
    """Raised when a Steam VDF/ACF document is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class SteamAppInstallation:
    app_id: str
    name: str
    install_dir: str
    root: Path
    library_root: Path
    manifest_path: Path
    build_id: str | None = None
    state_flags: str | None = None


def discover_windows_steam_roots() -> tuple[Path, ...]:
    """Return existing Steam roots from environment, registry, and defaults."""

    candidates: list[Path] = []
    environment_path = os.environ.get("STEAM_PATH")
    if environment_path:
        candidates.append(Path(environment_path))

    registry_locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
    )
    for hive, key_name in registry_locations:
        try:
            with winreg.OpenKey(hive, key_name) as key:
                for value_name in ("SteamPath", "InstallPath"):
                    try:
                        value, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    if isinstance(value, str) and value.strip():
                        candidates.append(Path(value))
        except OSError:
            continue

    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "Steam")
    return tuple(path for path in _deduplicate_paths(candidates) if path.is_dir())


def parse_vdf(text: str) -> dict[str, Any]:
    """Parse the object subset used by Steam VDF and ACF files."""

    if not isinstance(text, str):
        raise TypeError("VDF input must be text")
    tokens = _tokenize_vdf(text)
    document = _parse_vdf_object(tokens, depth=0, expect_closing=False)
    try:
        extra = next(tokens)
    except StopIteration:
        return document
    raise VdfError(f"unexpected token after VDF document: {extra!r}")


def _read_vdf_file(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        raw = file.read(MAX_VDF_BYTES + 1)
    if len(raw) > MAX_VDF_BYTES:
        raise VdfError(f"Steam metadata file is too large: {path}")
    return parse_vdf(raw.decode("utf-8-sig"))


def _read_app_manifest(
    manifest_path: Path,
    library_root: Path,
    expected_app_id: str,
) -> SteamAppInstallation:
    document = _read_vdf_file(manifest_path)
    app_state = document.get("AppState")
    if not isinstance(app_state, Mapping):
        raise VdfError("Steam app manifest is missing AppState")
    app_id = _required_string(app_state, "appid")
    if app_id != expected_app_id:
        raise VdfError(
            f"Steam app manifest declares app {app_id}, expected {expected_app_id}"
        )
    install_dir = _required_string(app_state, "installdir")
    relative = Path(install_dir)
    if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
        raise VdfError("Steam installdir must be one safe directory name")

    common_root = (library_root / "steamapps" / "common").resolve(strict=False)
    game_root = (common_root / relative).resolve(strict=False)
    try:
        game_root.relative_to(common_root)
    except ValueError as exc:
        raise VdfError("Steam app installation escapes the common directory") from exc

    return SteamAppInstallation(
        app_id=app_id,
        name=_optional_string(app_state, "name") or install_dir,
        install_dir=install_dir,
        root=game_root,
        library_root=library_root.resolve(strict=False),
        manifest_path=manifest_path.resolve(strict=False),
        build_id=_optional_string(app_state, "buildid"),
        state_flags=_optional_string(app_state, "StateFlags"),
    )


def _library_paths_from_document(document: Mapping[str, Any]) -> tuple[Path, ...]:
    folders = document.get("libraryfolders")
    if not isinstance(folders, Mapping):
        raise VdfError("libraryfolders.vdf is missing the libraryfolders object")
    paths: list[Path] = []
    for value in folders.values():
        if isinstance(value, str):
            path_value = value
        elif isinstance(value, Mapping):
            candidate = value.get("path")
            path_value = candidate if isinstance(candidate, str) else ""
        else:
            continue
        if path_value.strip():
            candidate_path = Path(path_value).expanduser()
            if candidate_path.is_absolute():
                paths.append(candidate_path.resolve(strict=False))
    return tuple(paths)


def _required_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise VdfError(f"Steam metadata is missing {key}")
    return value


def _optional_string(mapping: Mapping[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    return value if isinstance(value, str) and value else None


def _deduplicate_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = Path(path).expanduser().resolve(strict=False)
        key = os.path.normcase(os.path.normpath(str(normalized)))
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def _tokenize_vdf(text: str) -> Iterator[str]:
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = length if newline < 0 else newline + 1
            continue
        if character in "{}":
            yield character
            index += 1
            continue
        if character == '"':
            index += 1
            value: list[str] = []
            while index < length:
                character = text[index]
                if character == '"':
                    index += 1
                    yield "".join(value)
                    break
                if character == "\\":
                    index += 1
                    if index >= length:
                        raise VdfError("unterminated VDF escape sequence")
                    escaped = text[index]
                    value.append({"n": "\n", "r": "\r", "t": "\t"}.get(escaped, escaped))
                    index += 1
                    continue
                value.append(character)
                index += 1
            else:
                raise VdfError("unterminated quoted VDF string")
            continue

        start = index
        while index < length and not text[index].isspace() and text[index] not in '{}"':
            index += 1
        if start == index:
            raise VdfError(f"unexpected VDF character at offset {index}")
        yield text[start:index]


def _parse_vdf_object(
    tokens: Iterator[str],
    *,
    depth: int,
    expect_closing: bool,
) -> dict[str, Any]:
    if depth > MAX_VDF_DEPTH:
        raise VdfError("VDF nesting exceeds the safety limit")
    result: dict[str, Any] = {}
    while True:
        try:
            token = next(tokens)
        except StopIteration:
            if expect_closing:
                raise VdfError("unterminated VDF object")
            return result
        if token == "}":
            if not expect_closing:
                raise VdfError("unexpected closing brace in VDF document")
            return result
        if token == "{":
            raise VdfError("VDF object is missing a key")
        key = token
        try:
            value = next(tokens)
        except StopIteration:
            raise VdfError(f"VDF key {key!r} is missing a value") from None
        if value == "{":
            result[key] = _parse_vdf_object(
                tokens,
                depth=depth + 1,
                expect_closing=True,
            )
        elif value == "}":
            raise VdfError(f"VDF key {key!r} is missing a value")
        else:
            result[key] = value


class SteamInstallationLocator:
    """Locate installed Steam applications across configured libraries."""

    def __init__(self, steam_roots: Iterable[Path] | None = None) -> None:
        roots = (
            discover_windows_steam_roots()
            if steam_roots is None
            else tuple(Path(root) for root in steam_roots)
        )
        self._steam_roots = _deduplicate_paths(roots)

    def library_roots(self) -> tuple[Path, ...]:
        libraries: list[Path] = []
        for steam_root in self._steam_roots:
            normalized_root = steam_root.expanduser().resolve(strict=False)
            if normalized_root.is_dir():
                libraries.append(normalized_root)
            library_file = normalized_root / "steamapps" / "libraryfolders.vdf"
            if not library_file.is_file():
                continue
            try:
                document = _read_vdf_file(library_file)
                libraries.extend(_library_paths_from_document(document))
            except (OSError, UnicodeError, VdfError):
                continue
        return _deduplicate_paths(libraries)

    def find_app(self, app_id: str) -> tuple[SteamAppInstallation, ...]:
        if not isinstance(app_id, str) or not app_id.isdigit():
            raise ValueError("app_id must contain only decimal digits")
        found: list[SteamAppInstallation] = []
        for library in self.library_roots():
            manifest = library / "steamapps" / f"appmanifest_{app_id}.acf"
            if not manifest.is_file():
                continue
            try:
                installation = _read_app_manifest(manifest, library, app_id)
            except (OSError, UnicodeError, VdfError):
                continue
            if installation.root.is_dir():
                found.append(installation)
        return tuple(found)


# ---------------------------------------------------------------------------
# Auto-detection of the Cities: Skylines II game root
# ---------------------------------------------------------------------------

def _auto_detect_game_dirs(steam_roots: list[Path] | None = None) -> list[Path]:
    locator = SteamInstallationLocator(steam_roots)
    found: list[Path] = []
    for installation in locator.find_app(CS2_APPID):
        if installation.root.is_dir():
            found.append(installation.root)
    # Fallback: scan common folder names when the manifest is unavailable.
    if not found:
        for library in locator.library_roots():
            for candidate in GAME_FOLDER_CANDIDATES:
                game_dir = library / "common" / candidate
                if game_dir.is_dir():
                    found.append(game_dir)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in found:
        normalized = path.resolve(strict=False)
        key = os.path.normcase(str(normalized))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def _list_entries(directory: Path, limit: int = 300) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    try:
        children = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError as exc:
        return [{"error": str(exc)}]
    for child in children[:limit]:
        try:
            is_dir = child.is_dir()
        except OSError:
            is_dir = False
        try:
            size = child.stat().st_size
        except OSError:
            size = 0
        entries.append(
            {
                "name": child.name,
                "type": "dir" if is_dir else "file",
                "size_bytes": 0 if is_dir else size,
                "size_human": "" if is_dir else _fmt_size(size),
            }
        )
    return entries


def _key_file(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    exists = path.exists()
    size_human = ""
    if exists and path.is_file():
        try:
            size_human = _fmt_size(path.stat().st_size)
        except OSError:
            size_human = ""
    return {
        "relative": relative,
        "exists": exists,
        "type": "dir" if path.is_dir() else "file",
        "size_human": size_human,
        "absolute": str(path),
    }


def _probe(root: Path) -> dict[str, object]:
    content_dir = root / "Cities2_Data" / "Content"
    key_files = [
        "Cities2.exe",
        "Cities2_Data",
        "Cities2_Data/Plugins/x86_64",
        "Cities2_Data/Plugins/x86_64/steam_api64.dll",
        "Cities2_Data/Managed",
        "Cities2_Data/Content",
        "launcher.exe",
        "Cities2_Data/StreamingAssets",
    ]
    report = {
        "game_root": str(root.resolve()),
        "detected_by": "auto" if True else "manual",
        "generated_at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "root_entries": _list_entries(root),
        "dlc_content_entries": _list_entries(content_dir) if content_dir.is_dir() else [],
        "key_files": {relative: _key_file(root, relative) for relative in key_files},
    }
    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _render_text(report: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("=" * 58)
    lines.append(" 城市天际线2（Cities: Skylines II）目录探测报告")
    lines.append("=" * 58)
    lines.append("")
    lines.append(f"生成时间：{report['generated_at']}")
    lines.append(f"游戏根目录：{report['game_root']}")
    lines.append("")

    lines.append(f"[1] 根目录内容（共 {len(report['root_entries'])} 项）")
    lines.append("-" * 58)
    if not report["root_entries"]:
        lines.append("    （空目录或无法读取）")
    for entry in report["root_entries"]:  # type: ignore[union-attr]
        kind = "[DIR]" if entry["type"] == "dir" else "[FILE]"
        size = f"  {entry['size_human']}" if entry.get("size_human") else ""
        lines.append(f"    {kind}  {entry['name']}{size}")
    lines.append("")

    dlc_entries = report["dlc_content_entries"]  # type: ignore[assignment]
    lines.append(f"[2] DLC 内容目录 Cities2_Data\\Content（共 {len(dlc_entries)} 项）")
    lines.append("-" * 58)
    if not dlc_entries:
        lines.append("    （不存在或为空：可能没有安装任何 DLC，或游戏目录不完整）")
    for entry in dlc_entries:
        kind = "[DIR]" if entry["type"] == "dir" else "[FILE]"
        size = f"  {entry['size_human']}" if entry.get("size_human") else ""
        lines.append(f"    {kind}  {entry['name']}{size}")
    lines.append("")

    lines.append("[3] 关键文件检查")
    lines.append("-" * 58)
    key_files = report["key_files"]  # type: ignore[assignment]
    for relative, info in key_files.items():
        if info["exists"]:
            marker = "[存在]"
        else:
            marker = "[缺失]"
        size = f"  {info['size_human']}" if info.get("size_human") else ""
        lines.append(f"    {marker}  {relative}{size}")
        lines.append(f"            {info['absolute']}")
    lines.append("")
    lines.append("=" * 58)
    lines.append("请把本文件（以及同目录下的 .json 文件）发回给唏嘘南溪，谢谢！")
    lines.append("=" * 58)
    return "\n".join(lines)


def _write_reports(report: dict[str, object], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = out_dir / f"{OUTPUT_PREFIX}_{stamp}.txt"
    json_path = out_dir / f"{OUTPUT_PREFIX}_{stamp}.json"
    txt_path.write_text(_render_text(report), encoding="utf-8-sig", newline="\r\n")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return txt_path, json_path


# ---------------------------------------------------------------------------
# Interactive entry point
# ---------------------------------------------------------------------------

def _safe_input(prompt: str) -> str | None:
    """input() that never raises on a closed/EOF console (returns None)."""
    try:
        return input(prompt)
    except EOFError:
        return None


def _pick_game_dir(candidates: list[Path]) -> Path | None:
    print(f"检测到 {len(candidates)} 个可能的城市天际线2 目录：\n")
    for index, candidate in enumerate(candidates, start=1):
        print(f"  [{index}] {candidate}")
    print("\n如果上面有你的游戏目录，请输入对应数字；")
    print("如果没有，直接回车，然后手动输入游戏根目录路径。")
    while True:
        choice = _safe_input("\n请输入数字或直接回车：")
        if choice is None:
            return None
        choice = choice.strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1]
        print("输入无效，请重新输入。")


def _manual_path() -> Path | None:
    print("\n请把游戏根目录路径粘贴进来（也可以把文件夹直接拖进本窗口）。")
    print("游戏根目录通常类似：D:\\SteamLibrary\\steamapps\\common\\Cities Skylines II")
    raw = _safe_input("游戏根目录：")
    if raw is None:
        return None
    raw = raw.strip().strip('"')
    if not raw:
        return None
    path = Path(raw)
    if not path.is_dir():
        print(f"\n[错误] 找不到该目录：{path}")
        return None
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="探测城市天际线2 安装目录并生成报告")
    parser.add_argument("--path", help="直接指定游戏根目录，跳过自动检测")
    parser.add_argument("--out", help="报告输出目录（默认程序所在目录）")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else _default_out_dir()
    game_dir: Path | None = None
    detected_by = "manual"
    if args.path:
        game_dir = Path(args.path)
        if not game_dir.is_dir():
            print(f"[错误] --path 指向的目录不存在：{game_dir}")
            return 1
        detected_by = "explicit"
    else:
        candidates = _auto_detect_game_dirs()
        if len(candidates) == 1:
            game_dir = candidates[0]
            detected_by = "auto"
            print(f"自动检测到游戏目录：{game_dir}")
        elif len(candidates) > 1:
            game_dir = _pick_game_dir(candidates)
            detected_by = "auto"
        if game_dir is None:
            print("\n未自动检测到城市天际线2 的安装目录。")
            for _attempt in range(3):
                game_dir = _manual_path()
                if game_dir is not None:
                    break
        if game_dir is None:
            print("未提供游戏目录，退出。")
            return 1

    print(f"\n正在扫描：{game_dir}")
    report = _probe(game_dir)
    report["detected_by"] = detected_by
    txt_path, json_path = _write_reports(report, out_dir)
    print("\n" + _render_text(report))
    print(f"\n报告已生成：\n  {txt_path}\n  {json_path}")
    print("\n请把上面这两个文件发回给唏嘘南溪，谢谢！")
    return 0


if __name__ == "__main__":
    _utf8_console()
    try:
        raise SystemExit(_pause_exit(main()))
    except KeyboardInterrupt:
        print("\n已取消。")
        _safe_input("")
        raise SystemExit(130)
    except Exception:  # keep the window open so the user can report the error
        import traceback

        print("\n[错误] 程序运行出错，请把下面信息截图发给唏嘘南溪：")
        traceback.print_exc()
        _safe_input("\n按回车键关闭窗口。")
        raise SystemExit(1)
