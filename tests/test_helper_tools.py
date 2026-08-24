from pathlib import Path
import io
import threading
import zipfile

import pytest

from signriver_app.application.guides import GuideTool
from signriver_app.application.helper_tools import (
    HelperToolCancelled,
    HelperToolError,
    HelperToolsService,
)
from signriver_app.infrastructure.catalog import fixed_release_asset_url


def _tool(**overrides) -> GuideTool:
    payload = {
        "tool_id": "dcontrol",
        "title": "dControl",
        "description": "helper",
        "asset_name": "dControl.zip",
        "release_tag": "tools",
        "package_kind": "zip",
        "launch_action": "exe",
        "executable_name": "dControl.exe",
        "run_as_admin": True,
        "platforms": ["windows"],
    }
    payload.update(overrides)
    return GuideTool.from_dict(payload)


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def test_helper_tool_urls_follow_current_download_source() -> None:
    tool = _tool()
    gitlink = HelperToolsService(Path("unused"), download_source="gitlink")
    github = HelperToolsService(Path("unused"), download_source="github")
    assert gitlink.resolve_url(tool) == (
        "https://gitlink.org.cn/signriver/signriver-dlc-assets/releases/download/tools/dControl.zip"
    )
    assert github.resolve_url(tool) == (
        "https://github.com/sign-river/signriver-dlc-assets/releases/download/tools/dControl.zip"
    )
    assert gitlink.resolve_url(tool) == fixed_release_asset_url("gitlink", "tools", "dControl.zip")


def test_helper_tool_download_extracts_zip_and_finds_exe(tmp_path: Path) -> None:
    payload = _zip_bytes({"dControl/dControl.exe": b"mz"})
    service = HelperToolsService(
        tmp_path / "helper-tools",
        opener=lambda _url, _timeout: payload,
    )
    tool = _tool()
    dest = service.download(tool)
    assert dest == tmp_path / "helper-tools" / "dcontrol"
    assert service.is_installed(tool)
    exe = service.find_executable(tool)
    assert exe is not None
    assert exe.name == "dControl.exe"
    assert exe.read_bytes() == b"mz"
    assert not (dest / "dControl.zip").exists()
    service.delete(tool.tool_id)
    assert not service.is_installed(tool)
    assert not dest.exists()


def test_helper_tool_cancel_deletes_partial_download(tmp_path: Path) -> None:
    cancel = threading.Event()

    def opener(_url, _timeout, event=None):
        if event is not None:
            event.set()
        raise HelperToolCancelled("已取消下载")

    service = HelperToolsService(tmp_path / "helper-tools", opener=opener)
    tool = _tool()
    with pytest.raises(HelperToolCancelled):
        service.download(tool, cancel)
    assert not service.tool_dir(tool.tool_id).exists()
    assert not service.is_installed(tool)


def test_helper_tool_revision_marks_old_download_stale_and_replaces_safely(tmp_path: Path) -> None:
    payloads = [b"old", b"new"]
    service = HelperToolsService(
        tmp_path / "helper-tools", opener=lambda *_args: payloads.pop(0)
    )
    old = _tool(
        revision="2026-08-24", asset_name="", filename="repair.ps1", download_url="https://example.invalid/repair.ps1",
        package_kind="file", launch_action="legacy", executable_name="",
    )
    new = _tool(
        revision="2026-08-25", asset_name="", filename="repair.ps1", download_url="https://example.invalid/repair.ps1",
        package_kind="file", launch_action="legacy", executable_name="",
    )
    service.download(old)
    assert service.is_installed(old)
    assert not service.is_installed(new)
    service.download(new)
    assert service.is_installed(new)
    assert (service.tool_dir(new.tool_id) / "repair.ps1").read_bytes() == b"new"


def test_helper_tool_rejects_zip_slip(tmp_path: Path) -> None:
    payload = _zip_bytes({"../evil.exe": b"bad"})
    service = HelperToolsService(
        tmp_path / "helper-tools",
        opener=lambda _url, _timeout: payload,
    )
    with pytest.raises(HelperToolError, match="不安全路径"):
        service.download(_tool())
    assert not (tmp_path / "helper-tools" / "dcontrol").exists()
