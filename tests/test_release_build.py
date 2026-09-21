import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from tools import build_release
from tools.build_release import build_full_update_archive, write_release_manifest


def _sfx_payload_paths(sfx_path) -> list[str]:
    """用 7-Zip 列出 SFX 的 payload 路径（Bandizip 的 SFX 是 ZIP+stub，7z 也能列）。"""
    seven_zip = build_release._find_7z()
    if seven_zip is None:
        pytest.skip("缺少 7-Zip，无法列出 SFX payload")
    listing = subprocess.run(
        # -sccUTF-8：7z 默认按控制台代码页输出，中文目录名会变成乱码。
        [str(seven_zip), "l", "-slt", "-sccUTF-8", str(sfx_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    payload = re.split(r"-{10,}\r?\n", listing, maxsplit=1)[-1]
    return [
        line.split(" = ", 1)[1].strip()
        for line in payload.splitlines()
        if line.startswith("Path = ")
    ]


def _sfx_backend_available() -> bool:
    """是否存在能真正产出 SFX 的后端（只有 7z 主程序不够，还要 7z.sfx 模块）。"""
    bandizip = build_release._find_bandizip()
    if bandizip is not None and (bandizip.parent / "bdzsfx.x86.sfx").is_file():
        return True
    seven_zip = build_release._find_7z()
    return seven_zip is not None and (seven_zip.parent / "7z.sfx").is_file()


def test_sfx_payload_keeps_the_release_folder(tmp_path) -> None:
    """自解压包必须把整个发布文件夹打进去，解压时不得散落到目标目录。

    回归背景：payload 曾用 ``.\\<发布目录>\\*`` 只打目录内容，用户在盘根
    目录解压时会把文件铺满整个盘。
    """
    if not _sfx_backend_available():
        pytest.skip("本机没有可用的自解压后端（7-Zip 需带 7z.sfx / Bandizip）")
    dist = tmp_path / "dist"
    release = dist / build_release.RELEASE_DIR_NAME
    release.mkdir(parents=True)
    (release / build_release.RELEASE_EXE_NAME).write_bytes(b"MZ")
    (release / "使用说明.txt").write_text("exe 与 app、config 同目录", encoding="utf-8")
    sfx_path = dist / "release-sfx.exe"

    assert build_release._build_sfx(release, dist / "release.7z", sfx_path) is True

    paths = _sfx_payload_paths(sfx_path)

    assert paths
    for path in paths:
        assert path.replace("/", "\\").startswith(build_release.RELEASE_DIR_NAME), path


def test_bandizip_sfx_payload_extracts_into_a_single_folder(tmp_path) -> None:
    """Bandizip 自解压包的 payload 解出来只应出现发布文件夹。

    这里用 7-Zip 解 payload（Bandizip 的 SFX 本体是 ZIP + stub），避免测试
    去启动图形界面的 SFX——那条路径会弹窗等待用户点击。
    """
    bandizip = build_release._find_bandizip()
    if bandizip is None or not (bandizip.parent / "bdzsfx.x86.sfx").is_file():
        pytest.skip("本机未安装 Bandizip，跳过自解压落点用例")
    seven_zip = build_release._find_7z()
    if seven_zip is None:
        pytest.skip("缺少 7-Zip，无法解出自解压包 payload")
    release = tmp_path / "payload" / build_release.RELEASE_DIR_NAME
    (release / "app").mkdir(parents=True)
    (release / build_release.RELEASE_EXE_NAME).write_bytes(b"MZ")
    (release / "app" / "state.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    sfx_path = output / f"{build_release.RELEASE_DIR_NAME}-自解压.exe"

    assert build_release._build_bandizip_sfx(release, sfx_path) is True

    target = tmp_path / "target"
    target.mkdir()
    subprocess.run(
        [str(seven_zip), "x", str(sfx_path), f"-o{target}", "-y"],
        check=True,
        capture_output=True,
    )

    assert sorted(item.name for item in target.iterdir()) == [
        build_release.RELEASE_DIR_NAME
    ]
    extracted = target / build_release.RELEASE_DIR_NAME
    assert (extracted / build_release.RELEASE_EXE_NAME).is_file()
    assert (extracted / "app" / "state.json").is_file()


def test_release_build_analyzes_external_application_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        build_release,
        "APP_VERSION_ROOT",
        build_release.ROOT / "app" / "versions" / "0.1.0",
    )
    imports = build_release.application_hidden_imports()
    assert "webbrowser" in imports
    assert "signriver_app.infrastructure.persistence.database" in imports
    assert "signriver_app.infrastructure.installs.engine" in imports
    assert "signriver_app.application.download_queue" in imports


def test_release_build_excludes_unused_numpy_runtime() -> None:
    assert build_release.pyinstaller_exclude_args() == [
        "--exclude-module",
        "numpy",
    ]


def test_full_release_manifest_excludes_user_state(tmp_path) -> None:
    (tmp_path / "app").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "app" / "state.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "update.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config" / "publisher.local.json").write_text(
        '{"token": "private"}', encoding="utf-8"
    )
    (tmp_path / "launcher.exe").write_bytes(b"launcher")
    manifest = json.loads(write_release_manifest(tmp_path, "0.2.0").read_text(encoding="utf-8"))
    assert manifest["version"] == "0.2.0"
    assert [item["path"] for item in manifest["files"]] == ["launcher.exe"]


def test_release_package_carries_only_the_active_module_and_one_fallback() -> None:
    """随包发布的模块只有当前版本 + 最近一个已发布版本。

    回归背景：``app/versions`` 会累积历史上所有模块目录，逐个打进包里只是
    白占体积——运行哪个版本只由 ``app/state.json`` 决定，旧版本唯一的用处是
    激活模块加载失败时给启动器一个回退目标。
    """
    versions = build_release.packaged_module_versions()
    assert versions[0] == build_release.APP_VERSION
    assert 1 <= len(versions) <= 2
    for name in versions:
        assert (
            build_release.ROOT / "app" / "versions" / name / "module.json"
        ).is_file()


def test_release_copy_skips_historical_module_directories() -> None:
    versions_root = build_release.ROOT / "app" / "versions"
    names = [item.name for item in versions_root.iterdir() if item.is_dir()]
    kept = set(names) - set(build_release._app_tree_ignore(str(versions_root), names))

    assert kept == set(build_release.packaged_module_versions())
    # 0.1.0 只是仓库里的源码基线，不是发行版本，不应随包发布。
    if build_release.APP_VERSION != "0.1.0":
        assert "0.1.0" not in kept


def test_copy_app_tree_limits_module_directories(tmp_path) -> None:
    destination = tmp_path / "app"

    build_release.copy_app_tree(destination)

    copied = sorted(
        item.name for item in (destination / "versions").iterdir() if item.is_dir()
    )
    assert copied == sorted(build_release.packaged_module_versions())
    assert (destination / "state.json").is_file()


def _prepare_publisher_inbox_fixture(tmp_path, version: str = "9.9.9") -> dict:
    """搭一个最小的 dist + 发布器收件目录，供同步测试使用。"""
    (tmp_path / "dist" / "updates").mkdir(parents=True)
    (tmp_path / "dist" / "modules").mkdir(parents=True)
    package = tmp_path / "dist" / "updates" / (
        f"SignRiver-DLC-Hub-full-v{version}-windows-x64.zip"
    )
    package.write_bytes(b"package")
    module = tmp_path / "dist" / "modules" / f"SignRiver-DLC-Hub-module-v{version}.zip"
    module.write_bytes(b"module")
    source = tmp_path / "app" / "versions" / version
    source.mkdir(parents=True)
    (source / "app_entry.py").write_text("x", encoding="utf-8")
    inbox = tmp_path / "publisher-workspace" / "output"
    (inbox / "updates").mkdir(parents=True)
    (inbox / "modules").mkdir(parents=True)
    return {"package": package, "module": module, "source": source, "inbox": inbox}


def test_sync_publisher_inbox_copies_fresh_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    fixture = _prepare_publisher_inbox_fixture(tmp_path)
    os.utime(fixture["source"] / "app_entry.py", (1, 1))
    os.utime(fixture["module"], (100, 100))

    copied = build_release.sync_publisher_inbox(version="9.9.9")

    assert [path.name for path in copied] == [
        fixture["package"].name,
        fixture["module"].name,
    ]
    assert (fixture["inbox"] / "updates" / fixture["package"].name).read_bytes() == (
        b"package"
    )
    assert (fixture["inbox"] / "modules" / fixture["module"].name).read_bytes() == (
        b"module"
    )


def test_sync_publisher_inbox_skips_stale_module_archive(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    fixture = _prepare_publisher_inbox_fixture(tmp_path)
    # 源码比模块归档新：说明归档是上一次构建的产物，不能带进发布。
    os.utime(fixture["module"], (1, 1))
    os.utime(fixture["source"] / "app_entry.py", (100, 100))

    copied = build_release.sync_publisher_inbox(version="9.9.9")

    assert [path.name for path in copied] == [fixture["package"].name]
    assert not (fixture["inbox"] / "modules" / fixture["module"].name).exists()
    assert "跳过模块归档同步" in capsys.readouterr().out


def test_sync_publisher_inbox_ignores_runtime_pycache(tmp_path, monkeypatch) -> None:
    """`__pycache__` 里的 .pyc 比归档新时，不能误判归档过期。"""
    monkeypatch.setattr(build_release, "ROOT", tmp_path)
    fixture = _prepare_publisher_inbox_fixture(tmp_path)
    os.utime(fixture["source"] / "app_entry.py", (1, 1))
    os.utime(fixture["module"], (100, 100))
    cache = fixture["source"] / "__pycache__"
    cache.mkdir()
    (cache / "app_entry.cpython-311.pyc").write_bytes(b"pyc")
    os.utime(cache / "app_entry.cpython-311.pyc", (500, 500))

    copied = build_release.sync_publisher_inbox(version="9.9.9")

    assert [path.name for path in copied] == [
        fixture["package"].name,
        fixture["module"].name,
    ]


def test_sync_publisher_inbox_without_publisher_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_release, "ROOT", tmp_path)

    assert build_release.sync_publisher_inbox() == []
    assert not (tmp_path / "publisher-workspace").exists()


def test_bandizip_sfx_language_block_is_localized(tmp_path) -> None:
    """Bandizip 自解压对话框的 [LANG] 块要被换成中文。

    `bz.exe` 按打包机的界面语言把文案作为 UTF-8 文本块追加在 SFX 末尾，默认
    是英文；发布包统一替换成中文，保持用户看到一致的中文界面。
    """
    sfx = tmp_path / "release-sfx.exe"
    english_block = (
        b"\xef\xbb\xbf[LANG]\r\n"
        b"STATIC_TARGET_PATH\t= Target Path :\r\n"
        b"MSG_COMPLETED\t\t\t= Extraction successful!\r\n"
    )
    sfx.write_bytes(b"MZ payload" + english_block)

    assert build_release.localize_bandizip_sfx_language(sfx) is True

    data = sfx.read_bytes()
    assert data.startswith(b"MZ payload")
    assert "目标路径".encode("utf-8") in data
    assert "解压完成！".encode("utf-8") in data
    assert b"Target Path" not in data
    assert data.endswith("否\r\n".encode("utf-8"))


def test_bandizip_sfx_language_block_missing_keeps_file_untouched(tmp_path) -> None:
    sfx = tmp_path / "plain-sfx.exe"
    sfx.write_bytes(b"MZ payload without language block")
    before = sfx.read_bytes()

    assert build_release.localize_bandizip_sfx_language(sfx) is False
    assert sfx.read_bytes() == before


def test_bandizip_sfx_payload_ignores_relative_parent_directory(
    tmp_path, monkeypatch
) -> None:
    """用相对路径传发布目录时，外层目录名（例如 dist）不能被打进 payload。

    回归背景：手工重建自解压包时传入 ``dist/<发布目录>``，Bandizip 把 ``dist\\``
    一起存进了 payload，用户解压后凭空多出一层目录。
    """
    bandizip = build_release._find_bandizip()
    if bandizip is None or not (bandizip.parent / "bdzsfx.x86.sfx").is_file():
        pytest.skip("本机未安装 Bandizip，跳过自解压 payload 用例")
    if build_release._find_7z() is None:
        pytest.skip("缺少 7-Zip，无法列出 SFX payload")
    work = tmp_path / "work"
    release = work / "dist" / build_release.RELEASE_DIR_NAME
    (release / "app").mkdir(parents=True)
    (release / "app" / "state.json").write_text("{}", encoding="utf-8")
    (release / build_release.RELEASE_EXE_NAME).write_bytes(b"MZ")
    sfx_path = work / "out.exe"
    monkeypatch.chdir(work)

    assert build_release._build_bandizip_sfx(
        Path("dist") / build_release.RELEASE_DIR_NAME, sfx_path
    )

    tops: set[str] = set()
    for entry in _sfx_payload_paths(sfx_path):
        parts = entry.replace("/", "\\").split("\\")
        if parts[-1] == sfx_path.name:
            continue
        tops.add(parts[0])
    assert tops == {build_release.RELEASE_DIR_NAME}


def test_full_update_archive_is_flat_and_contains_only_managed_files(
    tmp_path,
) -> None:
    release = tmp_path / "release"
    (release / "app").mkdir(parents=True)
    (release / "config").mkdir()
    (release / "app" / "managed.txt").write_text("managed", encoding="utf-8")
    (release / "app" / "state.json").write_text("{}", encoding="utf-8")
    (release / "config" / "update.json").write_text("{}", encoding="utf-8")
    write_release_manifest(release, "0.2.0")

    archive = build_full_update_archive(
        release, tmp_path / "full-v0.2.0.zip", "0.2.0"
    )

    with zipfile.ZipFile(archive) as package:
        assert package.namelist() == [
            "release-manifest.json",
            "app/managed.txt",
        ]


def test_macos_manifest_stays_outside_signed_bundle(tmp_path) -> None:
    bundle = tmp_path / "SignRiver-DLC-Hub.app"
    binary = bundle / "Contents" / "MacOS" / "SignRiver-DLC-Hub"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"signed app")
    manifest_path = tmp_path / "payload" / "release-manifest.json"

    write_release_manifest(
        bundle,
        "0.2.0",
        target_platform="macos",
        manifest_path=manifest_path,
        path_prefix=bundle.name,
        bundle_path=bundle.name,
    )

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["bundle_path"] == bundle.name
    assert payload["files"][0]["path"] == (
        "SignRiver-DLC-Hub.app/Contents/MacOS/SignRiver-DLC-Hub"
    )
    assert not (bundle / "release-manifest.json").exists()
