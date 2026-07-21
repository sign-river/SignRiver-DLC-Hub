from __future__ import annotations

from pathlib import Path

from signriver_launcher.paths import RuntimePaths
from signriver_launcher.product import (
    AUTHOR_CN,
    AUTHOR_EN,
    PRODUCT_DISPLAY_NAME,
    RELEASE_DIR_NAME,
    RELEASE_EXE_NAME,
    RELEASE_SFX_NAME,
    RELEASE_ZIP_STEM,
    WINDOW_TITLE,
)


def test_release_product_names_are_chinese_and_path_safe() -> None:
    assert PRODUCT_DISPLAY_NAME == "唏嘘南溪DLC一键解锁工具"
    assert WINDOW_TITLE == "唏嘘南溪DLC一键解锁"
    assert AUTHOR_EN == "SignRiver"
    assert AUTHOR_CN == "唏嘘南溪"
    assert RELEASE_DIR_NAME == PRODUCT_DISPLAY_NAME
    assert RELEASE_EXE_NAME == f"{PRODUCT_DISPLAY_NAME}.exe"
    assert RELEASE_ZIP_STEM == PRODUCT_DISPLAY_NAME
    assert RELEASE_SFX_NAME == f"{PRODUCT_DISPLAY_NAME}-自解压.exe"
    for name in (RELEASE_DIR_NAME, RELEASE_EXE_NAME, RELEASE_ZIP_STEM):
        assert all(ch not in name for ch in '\\/:*?"<>|')
        assert " " not in name


def test_runtime_paths_support_chinese_install_root(tmp_path: Path) -> None:
    root = tmp_path / "工具" / "唏嘘南溪DLC一键解锁工具"
    paths = RuntimePaths(root)
    paths.ensure()
    assert paths.root == root
    assert paths.app_dir.is_dir()
    assert paths.data_dir.is_dir()
    assert paths.cache_dir.is_dir()
    marker = paths.data_dir / "中文设置.json"
    marker.write_text('{"ok": true}\n', encoding="utf-8")
    assert marker.read_text(encoding="utf-8") == '{"ok": true}\n'


def test_packaged_app_icon_exists_with_multiple_sizes() -> None:
    from PIL import Image

    icon = Path(__file__).parents[1] / "config" / "app.ico"
    assert icon.is_file()
    with Image.open(icon) as image:
        sizes = sorted(image.ico.sizes()) if image.ico is not None else []
    assert (16, 16) in sizes
    assert (20, 20) in sizes
    assert (32, 32) in sizes
    assert (40, 40) in sizes
    assert (256, 256) in sizes
    source = Path(__file__).parents[1] / "config" / "app.png"
    backup = Path(__file__).parents[1] / "config" / "app-icon-source.png"
    assert source.is_file()
    assert backup.read_bytes() == source.read_bytes()
