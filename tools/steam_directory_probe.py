"""Scan every installed Steam game and export complete directory structures.

This is a standalone, standard-library-only diagnostic tool.  It discovers
Steam libraries from the Windows registry and ``libraryfolders.vdf``, reads all
``appmanifest_*.acf`` files, then records every directory and file below each
installed game's root without reading file contents.

Examples:
    python steam_directory_probe.py
    python steam_directory_probe.py --game "Stellaris"
    python steam_directory_probe.py --game 949230 --out C:\\temp
    python steam_directory_probe.py --library D:\\SteamLibrary --no-pause
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


OUTPUT_PREFIX = "Steam游戏路径诊断报告"
MAX_VDF_BYTES = 4 * 1024 * 1024
MAX_VDF_DEPTH = 64

DLC_DIRECTORY_NAMES = {
    "addon",
    "addons",
    "content",
    "contents",
    "data",
    "downloadablecontent",
    "dlc",
    "dlcs",
    "expansion",
    "expansions",
    "files",
    "pack",
    "packs",
}
PATCH_DIRECTORY_NAMES = {
    "bin",
    "binaries",
    "plugin",
    "plugins",
    "steamsettings",
    "win32",
    "win64",
    "win64steam",
    "x8664",
}
PATCH_CONFIG_NORMALIZED_NAMES = {
    "creamapiini",
    "creamapijson",
    "icecreamini",
    "smokeapiconfigjson",
    "steamappidtxt",
}


class VdfError(ValueError):
    """Raised when Steam metadata is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class SteamGame:
    app_id: str
    name: str
    install_dir: str
    root: Path
    library_root: Path
    manifest_path: Path
    build_id: str | None = None
    state_flags: str | None = None


def _utf8_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if os.name == "nt":
        try:
            os.system("chcp 65001 >nul")
        except Exception:
            pass


def _safe_input(prompt: str) -> str | None:
    try:
        return input(prompt)
    except EOFError:
        return None


def _default_out_dir() -> Path:
    return (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )


def _deduplicate_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        normalized = Path(path).expanduser().resolve(strict=False)
        key = os.path.normcase(os.path.normpath(str(normalized)))
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return tuple(result)


def discover_windows_steam_roots() -> tuple[Path, ...]:
    candidates: list[Path] = []
    environment_path = os.environ.get("STEAM_PATH")
    if environment_path:
        candidates.append(Path(environment_path))

    try:
        import winreg
    except ImportError:
        winreg = None  # type: ignore[assignment]
    if winreg is not None:
        locations = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        )
        for hive, key_name in locations:
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
    if not isinstance(text, str):
        raise TypeError("VDF input must be text")
    tokens = _tokenize_vdf(text)
    result = _parse_vdf_object(tokens, depth=0, expect_closing=False)
    try:
        extra = next(tokens)
    except StopIteration:
        return result
    raise VdfError(f"unexpected token after VDF document: {extra!r}")


def _tokenize_vdf(text: str) -> Iterator[str]:
    index = 0
    while index < len(text):
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = len(text) if newline < 0 else newline + 1
            continue
        if character in "{}":
            yield character
            index += 1
            continue
        if character == '"':
            index += 1
            value: list[str] = []
            while index < len(text):
                character = text[index]
                if character == '"':
                    index += 1
                    yield "".join(value)
                    break
                if character == "\\":
                    index += 1
                    if index >= len(text):
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
        while index < len(text) and not text[index].isspace() and text[index] not in '{}"':
            index += 1
        if start == index:
            raise VdfError(f"unexpected VDF character at offset {index}")
        yield text[start:index]


def _parse_vdf_object(
    tokens: Iterator[str], *, depth: int, expect_closing: bool
) -> dict[str, Any]:
    if depth > MAX_VDF_DEPTH:
        raise VdfError("VDF nesting exceeds the safety limit")
    result: dict[str, Any] = {}
    while True:
        try:
            token = next(tokens)
        except StopIteration:
            if expect_closing:
                raise VdfError("unterminated VDF object") from None
            return result
        if token == "}":
            if not expect_closing:
                raise VdfError("unexpected closing brace in VDF document")
            return result
        if token == "{":
            raise VdfError("VDF object is missing a key")
        try:
            value = next(tokens)
        except StopIteration:
            raise VdfError(f"VDF key {token!r} is missing a value") from None
        if value == "{":
            result[token] = _parse_vdf_object(
                tokens, depth=depth + 1, expect_closing=True
            )
        elif value == "}":
            raise VdfError(f"VDF key {token!r} is missing a value")
        else:
            result[token] = value


def _read_vdf(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        raw = file.read(MAX_VDF_BYTES + 1)
    if len(raw) > MAX_VDF_BYTES:
        raise VdfError(f"Steam metadata file is too large: {path}")
    return parse_vdf(raw.decode("utf-8-sig"))


def _library_paths(document: Mapping[str, Any]) -> tuple[Path, ...]:
    folders = document.get("libraryfolders")
    if not isinstance(folders, Mapping):
        raise VdfError("libraryfolders.vdf is missing the libraryfolders object")
    paths: list[Path] = []
    for value in folders.values():
        candidate = value if isinstance(value, str) else value.get("path") if isinstance(value, Mapping) else None
        if isinstance(candidate, str) and candidate.strip():
            path = Path(candidate).expanduser()
            if path.is_absolute():
                paths.append(path)
    return _deduplicate_paths(paths)


def discover_library_roots(steam_roots: Iterable[Path]) -> tuple[tuple[Path, ...], list[str]]:
    libraries: list[Path] = []
    issues: list[str] = []
    for steam_root in _deduplicate_paths(steam_roots):
        if (steam_root / "steamapps").is_dir():
            libraries.append(steam_root)
        library_file = steam_root / "steamapps" / "libraryfolders.vdf"
        if not library_file.is_file():
            continue
        try:
            libraries.extend(_library_paths(_read_vdf(library_file)))
        except (OSError, UnicodeError, VdfError) as exc:
            issues.append(f"{library_file}: {exc}")
    return (
        tuple(path for path in _deduplicate_paths(libraries) if (path / "steamapps").is_dir()),
        issues,
    )


def _manifest_game(path: Path, library_root: Path) -> SteamGame:
    document = _read_vdf(path)
    state = document.get("AppState")
    if not isinstance(state, Mapping):
        raise VdfError("manifest is missing AppState")

    def required(key: str) -> str:
        value = state.get(key)
        if not isinstance(value, str) or not value:
            raise VdfError(f"manifest is missing {key}")
        return value

    app_id = required("appid")
    install_dir = required("installdir")
    relative = Path(install_dir)
    if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
        raise VdfError("Steam installdir must be one safe directory name")
    common_root = (library_root / "steamapps" / "common").resolve(strict=False)
    root = (common_root / relative).resolve(strict=False)
    try:
        root.relative_to(common_root)
    except ValueError as exc:
        raise VdfError("Steam installation escapes the common directory") from exc

    def optional(key: str) -> str | None:
        value = state.get(key)
        return value if isinstance(value, str) and value else None

    return SteamGame(
        app_id=app_id,
        name=optional("name") or install_dir,
        install_dir=install_dir,
        root=root,
        library_root=library_root.resolve(strict=False),
        manifest_path=path.resolve(strict=False),
        build_id=optional("buildid"),
        state_flags=optional("StateFlags"),
    )


def discover_games(libraries: Iterable[Path]) -> tuple[list[SteamGame], list[str]]:
    games: list[SteamGame] = []
    issues: list[str] = []
    for library in _deduplicate_paths(libraries):
        steamapps = library / "steamapps"
        try:
            manifests = sorted(steamapps.glob("appmanifest_*.acf"), key=lambda path: path.name)
        except OSError as exc:
            issues.append(f"{steamapps}: {exc}")
            continue
        for manifest in manifests:
            try:
                game = _manifest_game(manifest, library)
            except (OSError, UnicodeError, VdfError) as exc:
                issues.append(f"{manifest}: {exc}")
                continue
            if game.root.is_dir():
                games.append(game)
            else:
                issues.append(f"{manifest}: 游戏目录不存在：{game.root}")
    games.sort(key=lambda game: (game.name.casefold(), game.app_id, str(game.root)))
    return games, issues


def _matches_game(game: SteamGame, filters: list[str]) -> bool:
    if not filters:
        return True
    fields = (game.app_id.casefold(), game.name.casefold(), game.install_dir.casefold())
    return any(value.casefold() in field for value in filters for field in fields)


def _normalized_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _dlc_directory_reason(name: str) -> str | None:
    normalized = _normalized_name(name)
    if normalized.startswith("dlc"):
        return "名称包含 DLC"
    if normalized in {"addon", "addons", "expansion", "expansions"}:
        return "扩展内容目录"
    if normalized in DLC_DIRECTORY_NAMES:
        return "常见内容目录名"
    return None


def _is_patch_file(name: str) -> bool:
    lowered = name.casefold()
    normalized = _normalized_name(name)
    return (
        (lowered.startswith("steam_api") and lowered.endswith(".dll"))
        or (lowered.startswith("libsteam_api") and lowered.endswith((".so", ".dylib")))
        or lowered in {"steamclient.dll", "steamclient64.dll"}
        or normalized in PATCH_CONFIG_NORMALIZED_NAMES
        or normalized.startswith(("creamapi", "smokeapi", "icecream"))
    )


def _file_entry(relative: str, size: int) -> dict[str, object]:
    return {"path": relative, "size_bytes": size}


def _scan_tree(root: Path) -> tuple[dict[str, object], list[str]]:
    """Scan everything but retain only DLC, patch and executable path indexes."""
    issues: list[str] = []
    total_bytes = 0
    directory_count = 0
    file_count = 0
    directories: list[str] = []
    directory_children: dict[str, list[str]] = {}
    patch_files: list[dict[str, object]] = []
    executables: list[dict[str, object]] = []

    def visit(directory: Path, relative_directory: str = "") -> None:
        nonlocal total_bytes, directory_count, file_count
        try:
            children = list(os.scandir(directory))
            children.sort(key=lambda item: (not item.is_dir(follow_symlinks=False), item.name.casefold()))
        except OSError as exc:
            issues.append(f"{directory}: {exc}")
            return
        for child in children:
            path = Path(child.path)
            relative = path.relative_to(root).as_posix()
            try:
                is_link = child.is_symlink()
                is_dir = child.is_dir(follow_symlinks=False)
                if is_dir:
                    directory_count += 1
                    directories.append(relative)
                    directory_children.setdefault(relative_directory, []).append(relative)
                    visit(path, relative)
                else:
                    size = child.stat(follow_symlinks=False).st_size
                    total_bytes += size
                    file_count += 1
                    if _is_patch_file(child.name):
                        patch_files.append(_file_entry(relative, size))
                    if not is_link and path.suffix.casefold() == ".exe":
                        executables.append(_file_entry(relative, size))
            except OSError as exc:
                issues.append(f"{path}: {exc}")

    visit(root)
    dlc_directories: list[dict[str, object]] = []
    for relative in directories:
        reason = _dlc_directory_reason(Path(relative).name)
        if reason is None:
            continue
        parent_name = _normalized_name(Path(relative).parent.name)
        if parent_name in {"dlc", "dlcs"} and _normalized_name(Path(relative).name).startswith("dlc"):
            # The DLC root already lists these package directories as children.
            continue
        dlc_directories.append(
            {
                "path": relative,
                "reason": reason,
                "child_directories": directory_children.get(relative, []),
            }
        )

    patch_directory_reasons: dict[str, set[str]] = {}
    for relative in directories:
        if _normalized_name(Path(relative).name) in PATCH_DIRECTORY_NAMES:
            patch_directory_reasons.setdefault(relative, set()).add("常见补丁/二进制目录")
    for entry in patch_files:
        parent = Path(str(entry["path"])).parent.as_posix()
        patch_directory_reasons.setdefault("." if parent == "." else parent, set()).add(
            "包含 Steam API 或补丁配置"
        )
    patch_directories = [
        {"path": path, "reasons": sorted(reasons)}
        for path, reasons in sorted(patch_directory_reasons.items(), key=lambda item: item[0].casefold())
    ]
    return (
        {
            "scanned_directory_count": directory_count,
            "scanned_file_count": file_count,
            "total_file_bytes": total_bytes,
            "dlc_directories": dlc_directories,
            "patch_directories": patch_directories,
            "patch_files": patch_files,
            "executables": executables,
        },
        issues,
    )


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def build_report(libraries: Iterable[Path], games: Iterable[SteamGame], discovery_issues: list[str]) -> dict[str, object]:
    game_reports: list[dict[str, object]] = []
    for index, game in enumerate(games, start=1):
        print(f"[{index}] 正在扫描：{game.name}（AppID {game.app_id}）")
        path_index, scan_issues = _scan_tree(game.root)
        game_reports.append(
            {
                "app_id": game.app_id,
                "name": game.name,
                "install_dir": game.install_dir,
                "root": str(game.root),
                "library_root": str(game.library_root),
                "manifest_path": str(game.manifest_path),
                "build_id": game.build_id,
                "state_flags": game.state_flags,
                **path_index,
                "scan_issues": scan_issues,
            }
        )
    return {
        "report_format": 2,
        "report_scope": "完整扫描，仅保留 DLC、补丁、Steam API 和可执行文件路径",
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "libraries": [str(path) for path in libraries],
        "game_count": len(game_reports),
        "games": game_reports,
        "discovery_issues": discovery_issues,
    }


def _render_text(report: Mapping[str, object]) -> str:
    games = report["games"]
    assert isinstance(games, list)
    lines = [
        "=" * 72,
        " Steam 全游戏 DLC / 补丁路径诊断报告",
        "=" * 72,
        f"生成时间：{report['generated_at']}",
        f"Steam 库数量：{len(report['libraries'])}",  # type: ignore[arg-type]
        f"游戏数量：{report['game_count']}",
        "",
        "Steam 库：",
    ]
    lines.extend(f"  - {path}" for path in report["libraries"])  # type: ignore[union-attr]
    for game in games:
        assert isinstance(game, Mapping)
        lines.extend(
            [
                "",
                "=" * 72,
                f"{game['name']}（AppID {game['app_id']}）",
                f"根目录：{game['root']}",
                f"Build ID：{game['build_id'] or '未知'}",
                f"扫描统计：{game['scanned_directory_count']} 个目录，{game['scanned_file_count']} 个文件，{_human_size(int(game['total_file_bytes']))}",
                "-" * 72,
            ]
        )
        dlc_directories = game["dlc_directories"]
        assert isinstance(dlc_directories, list)
        lines.append("[DLC / 内容候选目录]")
        if not dlc_directories:
            lines.append("  （未按常见命名识别到候选目录）")
        for entry in dlc_directories:
            assert isinstance(entry, Mapping)
            lines.append(f"  [DIR] {entry['path']}  ({entry['reason']})")
            children = entry["child_directories"]
            assert isinstance(children, list)
            lines.extend(f"        └─ {child}" for child in children)

        patch_directories = game["patch_directories"]
        assert isinstance(patch_directories, list)
        lines.append("[补丁候选目录]")
        if not patch_directories:
            lines.append("  （未识别到）")
        for entry in patch_directories:
            assert isinstance(entry, Mapping)
            lines.append(f"  [DIR] {entry['path']}  ({'；'.join(entry['reasons'])})")  # type: ignore[arg-type]

        for title, key in (("Steam API / 补丁相关文件", "patch_files"), ("游戏可执行文件", "executables")):
            entries = game[key]
            assert isinstance(entries, list)
            lines.append(f"[{title}]")
            if not entries:
                lines.append("  （未识别到）")
            for entry in entries:
                assert isinstance(entry, Mapping)
                lines.append(f"  [FILE] {entry['path']}  {_human_size(int(entry['size_bytes']))}")
        scan_issues = game["scan_issues"]
        assert isinstance(scan_issues, list)
        if scan_issues:
            lines.append("  [读取问题]")
            lines.extend(f"    - {issue}" for issue in scan_issues)
    discovery_issues = report["discovery_issues"]
    assert isinstance(discovery_issues, list)
    if discovery_issues:
        lines.extend(["", "发现阶段的问题："])
        lines.extend(f"  - {issue}" for issue in discovery_issues)
    lines.extend(["", "=" * 72, "请把本文件和同名 .json 文件一起发回给维护者。", "=" * 72])
    return "\n".join(lines)


def _write_reports(report: Mapping[str, object], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = out_dir / f"{OUTPUT_PREFIX}_{stamp}.txt"
    json_path = out_dir / f"{OUTPUT_PREFIX}_{stamp}.json"
    txt_path.write_text(_render_text(report), encoding="utf-8-sig", newline="\r\n")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return txt_path, json_path


def _manual_library() -> Path | None:
    print("没有自动找到 Steam。请粘贴 Steam 安装目录或 Steam 库目录。")
    print(r"例如：C:\Program Files (x86)\Steam 或 D:\SteamLibrary")
    raw = _safe_input("目录：")
    if raw is None or not raw.strip():
        return None
    path = Path(raw.strip().strip('"')).expanduser()
    if not (path / "steamapps").is_dir():
        print(f"[错误] 该目录下没有 steamapps：{path}")
        return None
    return path.resolve(strict=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="扫描所有 Steam 游戏并导出完整目录结构")
    parser.add_argument("--game", action="append", default=[], help="只扫描名称、目录名或 AppID 包含此内容的游戏；可重复")
    parser.add_argument("--library", action="append", default=[], help="额外/指定 Steam 库根目录（其下应有 steamapps）；可重复")
    parser.add_argument("--steam-root", action="append", default=[], help="指定 Steam 安装目录；可重复")
    parser.add_argument("--out", help="报告输出目录（默认脚本所在目录）")
    parser.add_argument("--no-pause", action="store_true", help="完成后不等待按回车，适合命令行或自动化")
    args = parser.parse_args(argv)

    issues: list[str] = []
    if args.library:
        libraries = tuple(Path(value).expanduser().resolve(strict=False) for value in args.library)
        invalid = [path for path in libraries if not (path / "steamapps").is_dir()]
        if invalid:
            print("[错误] 以下目录不是有效 Steam 库：")
            for path in invalid:
                print(f"  {path}")
            return 2
    else:
        roots = [Path(value) for value in args.steam_root] if args.steam_root else list(discover_windows_steam_roots())
        libraries, issues = discover_library_roots(roots)
        if not libraries and not args.no_pause:
            manual = _manual_library()
            libraries = (manual,) if manual else ()
    if not libraries:
        print("[错误] 没有找到 Steam 库。可使用 --library 手动指定。")
        return 1

    games, game_issues = discover_games(libraries)
    issues.extend(game_issues)
    selected = [game for game in games if _matches_game(game, args.game)]
    if not selected:
        print("[错误] 没有找到匹配的已安装游戏。")
        if games:
            print("当前发现的游戏：")
            for game in games:
                print(f"  {game.name}（AppID {game.app_id}）")
        return 1

    print(f"发现 {len(libraries)} 个 Steam 库、{len(games)} 个已安装游戏；本次扫描 {len(selected)} 个。")
    report = build_report(libraries, selected, issues)
    out_dir = Path(args.out) if args.out else _default_out_dir()
    try:
        txt_path, json_path = _write_reports(report, out_dir)
    except OSError as exc:
        print(f"\n[错误] 无法把报告保存到程序所在目录：{out_dir}")
        print(f"系统信息：{exc}")
        print("请先把 ZIP 完整解压到桌面等可写目录，再运行其中的 EXE。")
        return 1
    print(f"\n扫描完成，报告就在本程序旁边：\n  {txt_path}\n  {json_path}")
    print("请把旁边这两个同名的 .txt 和 .json 文件一起发回给维护者。")
    if not args.no_pause:
        _safe_input("\n按回车键关闭窗口。")
    return 0


if __name__ == "__main__":
    _utf8_console()
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        raise SystemExit(130)
    except Exception:
        import traceback

        print("\n[错误] 程序运行出错，请把下面信息截图发给维护者：")
        traceback.print_exc()
        _safe_input("\n按回车键关闭窗口。")
        raise SystemExit(1)
