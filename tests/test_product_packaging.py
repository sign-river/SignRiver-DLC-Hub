from __future__ import annotations

from pathlib import Path

from signriver_launcher.paths import RuntimePaths
from signriver_launcher.product import (
    AUTHOR_CN,
    AUTHOR_EN,
    PRODUCT_DISPLAY_NAME,
    RELEASE_DIR_NAME,
    RELEASE_EXE_NAME,
    WINDOW_TITLE,
)


def test_release_product_names_are_chinese_and_path_safe() -> None:
    assert PRODUCT_DISPLAY_NAME == "星河DLC一键解锁"
    assert WINDOW_TITLE == PRODUCT_DISPLAY_NAME
    assert AUTHOR_EN == "SignRiver"
    assert AUTHOR_CN == "唏嘘南溪"
    assert RELEASE_DIR_NAME == PRODUCT_DISPLAY_NAME
    assert RELEASE_EXE_NAME == f"{PRODUCT_DISPLAY_NAME}.exe"
    for name in (RELEASE_DIR_NAME, RELEASE_EXE_NAME):
        assert all(ch not in name for ch in '\\/:*?"<>|')
        assert " " not in name


def test_runtime_paths_support_chinese_install_root(tmp_path: Path) -> None:
    root = tmp_path / "工具" / "星河DLC一键解锁"
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
    assert (256, 256) in sizes
    assert (Path(__file__).parents[1] / "config" / "app.png").is_file()
