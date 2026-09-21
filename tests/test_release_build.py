import json
import re
import subprocess
import zipfile

import pytest

from tools import build_release
from tools.build_release import build_full_update_archive, write_release_manifest


def test_sfx_payload_keeps_the_release_folder(tmp_path) -> None:
    """自解压包必须把整个发布文件夹打进去，解压时不得散落到目标目录。

    回归背景：payload 曾用 ``.\\<发布目录>\\*`` 只打目录内容，用户在盘根
    目录解压时会把文件铺满整个盘。
    """
    seven_zip = build_release._find_7z()
    if seven_zip is None:
        pytest.skip("本机未安装 7-Zip，跳过自解压包构建用例")
    dist = tmp_path / "dist"
    release = dist / build_release.RELEASE_DIR_NAME
    release.mkdir(parents=True)
    (release / build_release.RELEASE_EXE_NAME).write_bytes(b"MZ")
    (release / "使用说明.txt").write_text("exe 与 app、config 同目录", encoding="utf-8")
    sfx_path = dist / "release-sfx.exe"

    assert build_release._build_sfx(release, dist / "release.7z", sfx_path) is True

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
    paths = [
        line.split(" = ", 1)[1].strip()
        for line in payload.splitlines()
        if line.startswith("Path = ")
    ]

    assert paths, listing
    for path in paths:
        assert path.replace("/", "\\").startswith(build_release.RELEASE_DIR_NAME), path


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
