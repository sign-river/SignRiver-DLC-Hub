"""分析全部 Steam 游戏目录，收集 steam_api64.dll，并统一打包为 ZIP。

脚本只使用 Python 标准库，并复用同目录 ``steam_directory_probe.py`` 中的
Steam 定位和目录分析逻辑。一次运行会同时生成目录诊断报告、DLL 收集清单、
按游戏名归类的 DLL 文件夹，以及包含上述全部内容的 ZIP。

示例：
    python collect_steam_api64.py
    python collect_steam_api64.py --out D:\\SteamDllBackup --no-pause
    python collect_steam_api64.py --library E:\\SteamLibrary --no-pause
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

try:
    from tools.steam_directory_probe import (
        SteamGame,
        _deduplicate_paths,
        _write_reports,
        _safe_input,
        _utf8_console,
        build_report,
        discover_games,
        discover_library_roots,
        discover_windows_steam_roots,
    )
except ModuleNotFoundError:
    # 直接运行 tools/collect_steam_api64.py 时，脚本目录本身位于 sys.path。
    from steam_directory_probe import (  # type: ignore[no-redef]
        SteamGame,
        _deduplicate_paths,
        _write_reports,
        _safe_input,
        _utf8_console,
        build_report,
        discover_games,
        discover_library_roots,
        discover_windows_steam_roots,
    )


OUTPUT_PREFIX = "Steam_API64_DLL_收集"
DLL_NAME = "steam_api64.dll"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class LocatedDll:
    source: Path
    relative_path: Path


@dataclass(frozen=True, slots=True)
class CopyRecord:
    app_id: str
    game_name: str
    game_root: Path
    source: Path
    destination: Path
    size_bytes: int
    sha256: str


def _default_out_dir() -> Path:
    return (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent
    )


def _safe_folder_name(name: str, *, fallback: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", name).strip().rstrip(". ")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:120].rstrip(". ") or fallback


def _unique_game_folder_names(games: Iterable[SteamGame]) -> dict[SteamGame, str]:
    result: dict[SteamGame, str] = {}
    used: set[str] = set()
    for game in games:
        base = _safe_folder_name(game.name, fallback=f"Steam游戏_{game.app_id}")
        candidate = base
        suffix = 1
        while candidate.casefold() in used:
            label = game.app_id if suffix == 1 else f"{game.app_id}_{suffix}"
            candidate = _safe_folder_name(f"{base} (AppID {label})", fallback=label)
            suffix += 1
        used.add(candidate.casefold())
        result[game] = candidate
    return result


def _find_game_dlls(game: SteamGame) -> tuple[list[LocatedDll], list[str]]:
    dlls: list[LocatedDll] = []
    issues: list[str] = []
    root = game.root.resolve(strict=False)

    def onerror(error: OSError) -> None:
        location = getattr(error, "filename", None) or root
        issues.append(f"{game.name}: 无法读取 {location}: {error}")

    try:
        walker = os.walk(root, topdown=True, followlinks=False, onerror=onerror)
        for current, directories, files in walker:
            directories.sort(key=str.casefold)
            for filename in sorted(files, key=str.casefold):
                if filename.casefold() != DLL_NAME:
                    continue
                source = (Path(current) / filename).resolve(strict=False)
                try:
                    relative = source.relative_to(root)
                except ValueError:
                    issues.append(f"{game.name}: 已跳过游戏目录外的文件：{source}")
                    continue
                if source.is_file():
                    dlls.append(LocatedDll(source=source, relative_path=relative))
    except OSError as exc:
        issues.append(f"{game.name}: 扫描失败：{exc}")
    dlls.sort(key=lambda item: str(item.relative_path).casefold())
    return dlls, issues


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _next_output_dir(parent: Path) -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = parent / f"{OUTPUT_PREFIX}_{stamp}"
    index = 2
    while candidate.exists() or candidate.with_suffix(".zip").exists():
        candidate = parent / f"{OUTPUT_PREFIX}_{stamp}_{index}"
        index += 1
    return candidate


def collect_dlls(
    games: Iterable[SteamGame],
    output_dir: Path,
    *,
    located_dlls: Mapping[SteamGame, list[LocatedDll]] | None = None,
) -> tuple[list[CopyRecord], list[str], list[SteamGame]]:
    selected = list(games)
    folder_names = _unique_game_folder_names(selected)
    records: list[CopyRecord] = []
    issues: list[str] = []
    games_without_dll: list[SteamGame] = []

    located_by_game: list[tuple[SteamGame, list[LocatedDll]]] = []
    for game in selected:
        if located_dlls is None:
            dlls, scan_issues = _find_game_dlls(game)
            issues.extend(scan_issues)
        else:
            dlls = located_dlls.get(game, [])
        if dlls:
            located_by_game.append((game, dlls))
        else:
            games_without_dll.append(game)

    if not located_by_game:
        return records, issues, games_without_dll

    output_dir.mkdir(parents=True, exist_ok=False)
    for game, dlls in located_by_game:
        game_dir = output_dir / folder_names[game]
        for dll in dlls:
            destination = game_dir / dll.relative_path
            # 无论源文件大小写如何，归档内统一使用 Steam 的标准 DLL 文件名。
            destination = destination.with_name(DLL_NAME)
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(dll.source, destination)
                records.append(
                    CopyRecord(
                        app_id=game.app_id,
                        game_name=game.name,
                        game_root=game.root,
                        source=dll.source,
                        destination=destination,
                        size_bytes=destination.stat().st_size,
                        sha256=_sha256(destination),
                    )
                )
            except OSError as exc:
                issues.append(f"{game.name}: 复制 {dll.source} 失败：{exc}")

    if not records:
        shutil.rmtree(output_dir, ignore_errors=True)
    return records, issues, games_without_dll


def _dlls_from_directory_report(
    games: Iterable[SteamGame], report: Mapping[str, object]
) -> tuple[dict[SteamGame, list[LocatedDll]], list[str]]:
    games_by_key = {(game.app_id, str(game.root)): game for game in games}
    located: dict[SteamGame, list[LocatedDll]] = {}
    issues: list[str] = []
    game_reports = report.get("games")
    if not isinstance(game_reports, list):
        return located, ["目录分析报告缺少 games 列表"]

    for entry in game_reports:
        if not isinstance(entry, Mapping):
            continue
        game = games_by_key.get((str(entry.get("app_id", "")), str(entry.get("root", ""))))
        if game is None:
            continue
        scan_issues = entry.get("scan_issues")
        if isinstance(scan_issues, list):
            issues.extend(str(issue) for issue in scan_issues)
        patch_files = entry.get("patch_files")
        if not isinstance(patch_files, list):
            continue
        game_dlls: list[LocatedDll] = []
        for file_entry in patch_files:
            if not isinstance(file_entry, Mapping):
                continue
            relative_text = file_entry.get("path")
            if not isinstance(relative_text, str):
                continue
            relative = Path(relative_text)
            if relative.name.casefold() != DLL_NAME:
                continue
            source = (game.root / relative).resolve(strict=False)
            try:
                source.relative_to(game.root.resolve(strict=False))
            except ValueError:
                issues.append(f"{game.name}: 报告中的 DLL 路径越出游戏目录：{relative}")
                continue
            if source.is_file():
                game_dlls.append(LocatedDll(source=source, relative_path=relative))
            else:
                issues.append(f"{game.name}: 报告中的 DLL 已不存在：{source}")
        if game_dlls:
            located[game] = game_dlls
    return located, issues


def _write_manifest(
    output_dir: Path,
    libraries: Iterable[Path],
    records: Iterable[CopyRecord],
    games_without_dll: Iterable[SteamGame],
    issues: Iterable[str],
) -> Path:
    record_list = list(records)
    payload = {
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "libraries": [str(path) for path in libraries],
        "copied_dll_count": len(record_list),
        "game_count_with_dll": len({record.app_id for record in record_list}),
        "files": [
            {
                "app_id": record.app_id,
                "game_name": record.game_name,
                "game_root": str(record.game_root),
                "source": str(record.source),
                "archived_path": str(record.destination.relative_to(output_dir)),
                "size_bytes": record.size_bytes,
                "sha256": record.sha256,
            }
            for record in record_list
        ],
        "games_without_steam_api64_dll": [
            {
                "app_id": game.app_id,
                "game_name": game.name,
                "game_root": str(game.root),
            }
            for game in games_without_dll
        ],
        "issues": list(issues),
    }
    path = output_dir / "收集清单.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _make_zip(output_dir: Path) -> Path:
    archive = shutil.make_archive(
        str(output_dir),
        "zip",
        root_dir=output_dir.parent,
        base_dir=output_dir.name,
    )
    return Path(archive)


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


def _resolve_libraries(args: argparse.Namespace) -> tuple[tuple[Path, ...], list[str]]:
    if args.library:
        libraries = _deduplicate_paths(Path(value) for value in args.library)
        invalid = [path for path in libraries if not (path / "steamapps").is_dir()]
        if invalid:
            raise ValueError("以下目录不是有效 Steam 库：\n" + "\n".join(str(path) for path in invalid))
        return libraries, []

    roots = (
        [Path(value) for value in args.steam_root]
        if args.steam_root
        else list(discover_windows_steam_roots())
    )
    libraries, issues = discover_library_roots(roots)
    if not libraries and not args.no_pause:
        manual = _manual_library()
        libraries = (manual,) if manual else ()
    return libraries, issues


def _print_games_without_dll(games: Iterable[SteamGame]) -> None:
    missing = list(games)
    if not missing:
        return
    print(f"以下 {len(missing)} 个游戏未找到 {DLL_NAME}：")
    for game in missing:
        print(f"  - {game.name}（AppID {game.app_id}）")
        print(f"    目录：{game.root}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="分析全部 Steam 游戏目录，收集所有 steam_api64.dll，并统一压缩为 ZIP"
    )
    parser.add_argument(
        "--library",
        action="append",
        default=[],
        help="额外/指定 Steam 库根目录（其下应有 steamapps）；可重复",
    )
    parser.add_argument("--steam-root", action="append", default=[], help="指定 Steam 安装目录；可重复")
    parser.add_argument("--out", help="输出位置（默认脚本所在目录）")
    parser.add_argument("--no-pause", action="store_true", help="完成后不等待按回车")
    args = parser.parse_args(argv)

    try:
        libraries, issues = _resolve_libraries(args)
    except ValueError as exc:
        print(f"[错误] {exc}")
        return 2
    if not libraries:
        print("[错误] 没有找到 Steam 库。可使用 --library 手动指定。")
        return 1

    games, game_issues = discover_games(libraries)
    issues.extend(game_issues)
    if not games:
        print("[错误] 没有找到已安装的 Steam 游戏。")
        return 1

    print(f"发现 {len(libraries)} 个 Steam 库、{len(games)} 个已安装游戏。")
    print("正在执行完整目录分析，并从同一次扫描结果中提取 DLL……")
    directory_report = build_report(libraries, games, list(issues))
    located_dlls, report_issues = _dlls_from_directory_report(games, directory_report)
    issues.extend(report_issues)
    output_parent = Path(args.out).expanduser() if args.out else _default_out_dir()
    try:
        output_parent.mkdir(parents=True, exist_ok=True)
        output_dir = _next_output_dir(output_parent.resolve(strict=False))
        records, copy_issues, games_without_dll = collect_dlls(
            games, output_dir, located_dlls=located_dlls
        )
        issues.extend(copy_issues)
        if not records:
            print(f"[错误] 已扫描 {len(games)} 个游戏，但没有找到可复制的 {DLL_NAME}。")
            _print_games_without_dll(games_without_dll)
            if issues:
                print("扫描中还遇到以下问题：")
                for issue in issues:
                    print(f"  - {issue}")
            return 1
        report_txt, report_json = _write_reports(directory_report, output_dir)
        manifest = _write_manifest(output_dir, libraries, records, games_without_dll, issues)
        zip_path = _make_zip(output_dir)
    except OSError as exc:
        print(f"[错误] 创建收集目录或 ZIP 失败：{exc}")
        return 1

    games_with_dll = len({record.app_id for record in records})
    print(f"\n完成：从 {games_with_dll} 个游戏复制了 {len(records)} 个 DLL。")
    print(f"文件夹：{output_dir}")
    print(f"压缩包：{zip_path}")
    print(f"目录报告：{report_txt}")
    print(f"目录数据：{report_json}")
    print(f"DLL 清单：{manifest}")
    if games_without_dll:
        print()
        _print_games_without_dll(games_without_dll)
        print("以上游戏也已写入 DLL 收集清单。")
    if issues:
        print(f"扫描或复制过程中记录了 {len(issues)} 个问题，详情见清单。")
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

        print("\n[错误] 程序运行出错：")
        traceback.print_exc()
        _safe_input("\n按回车键关闭窗口。")
        raise SystemExit(1)
