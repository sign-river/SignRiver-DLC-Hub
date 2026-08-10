"""Probe a Cities: Skylines II installation and produce a directory report.

The report helps the maintainer determine:
- the game root directory
- DLC content folders under ``Cities2_Data\\Content``
- where ``Cities2.exe`` and ``steam_api64.dll`` live

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
import re
import sys
import winreg
from pathlib import Path

GAME_FOLDER_CANDIDATES = (
    "Cities Skylines II",
    "Cities Skylines 2",
    "Cities Skylines II - Cities2",
)
CS2_APPID = "949230"
OUTPUT_PREFIX = "CS2目录探测报告"


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


# ---------------------------------------------------------------------------
# Steam library auto-discovery
# ---------------------------------------------------------------------------

def _registry_steam_paths() -> list[Path]:
    paths: list[Path] = []
    roots = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    )
    for hive, key_path, value_name in roots:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
            if isinstance(value, str) and value.strip():
                paths.append(Path(value.strip()))
        except OSError:
            continue
    return paths


def _parse_library_folders(steam_root: Path) -> list[Path]:
    """Return steamapps library roots declared in libraryfolders.vdf."""
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if not vdf.is_file():
        return [steam_root / "steamapps"]
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [steam_root / "steamapps"]
    libs = [steam_root / "steamapps"]
    for match in re.finditer(r'"path"\s+"((?:[^"\\]|\\.)*)"', text):
        raw = match.group(1)
        unescaped = raw.replace(r"\\", "\\").replace(r"\"", '"')
        libs.append(Path(unescaped) / "steamapps")
    return libs


def _candidate_game_dirs(steam_roots: list[Path] | None = None) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    if steam_roots is None:
        steam_roots = _registry_steam_paths()
    if not steam_roots:
        # Common default locations as a fallback.
        steam_roots = [
            Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam",
        ]
    for steam_root in steam_roots:
        for library in _parse_library_folders(steam_root):
            for candidate in GAME_FOLDER_CANDIDATES:
                game_dir = library / "common" / candidate
                if game_dir.is_dir() and game_dir.resolve() not in seen:
                    seen.add(game_dir.resolve())
                    found.append(game_dir)
    return found


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
        entries.append(
            {
                "name": child.name,
                "type": "dir" if is_dir else "file",
                "size_bytes": 0 if is_dir else child.stat().st_size,
                "size_human": "" if is_dir else _fmt_size(child.stat().st_size),
            }
        )
    return entries


def _key_file(root: Path, relative: str) -> dict[str, object]:
    path = root / relative
    exists = path.exists()
    return {
        "relative": relative,
        "exists": exists,
        "type": "dir" if path.is_dir() else "file",
        "size_human": "" if not path.exists() else ("" if path.is_dir() else _fmt_size(path.stat().st_size)),
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

def _pick_game_dir(candidates: list[Path]) -> Path | None:
    print(f"自动检测到 {len(candidates)} 个可能的城市天际线2 目录：\n")
    for index, candidate in enumerate(candidates, start=1):
        print(f"  [{index}] {candidate}")
    print("\n如果上面有你的游戏目录，请输入对应数字；")
    print("如果没有，直接回车，然后手动输入游戏根目录路径。")
    while True:
        choice = input("\n请输入数字或直接回车：").strip()
        if not choice:
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1]
        print("输入无效，请重新输入。")


def _manual_path() -> Path | None:
    print("\n请把游戏根目录路径粘贴进来（也可以把文件夹直接拖进本窗口）。")
    print("游戏根目录通常类似：D:\\SteamLibrary\\steamapps\\common\\Cities Skylines II")
    raw = input("游戏根目录：").strip().strip('"')
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
    parser.add_argument("--out", help="报告输出目录（默认脚本所在目录）")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else Path(__file__).resolve().parent
    game_dir: Path | None = None
    if args.path:
        game_dir = Path(args.path)
        if not game_dir.is_dir():
            print(f"[错误] --path 指向的目录不存在：{game_dir}")
            return 1
    else:
        candidates = _candidate_game_dirs()
        if candidates:
            game_dir = _pick_game_dir(candidates)
        if game_dir is None:
            game_dir = _manual_path()
            while game_dir is None:
                game_dir = _manual_path()
        if game_dir is None:
            print("未提供游戏目录，退出。")
            return 1

    print(f"\n正在扫描：{game_dir}")
    report = _probe(game_dir)
    txt_path, json_path = _write_reports(report, out_dir)
    print("\n" + _render_text(report))
    print(f"\n报告已生成：\n  {txt_path}\n  {json_path}")
    print("\n请把上面这两个文件发回给唏嘘南溪，谢谢！")
    return 0


if __name__ == "__main__":
    _utf8_console()
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已取消。")
        raise SystemExit(130)
