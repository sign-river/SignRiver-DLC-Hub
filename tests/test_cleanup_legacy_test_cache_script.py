from pathlib import Path


SCRIPT = Path("tools/cleanup_legacy_test_cache.ps1")


def test_cleanup_script_is_preview_first_and_uses_an_exact_audited_allowlist() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    allowlist = source.split("$legacyNames = @(", 1)[1].split(")", 1)[0]

    assert "[switch]$Apply" in source
    assert "if (-not $Apply)" in source
    assert 'Read-Host "Type DELETE-TEST-CACHE to continue"' in source
    assert '"pytest-tmp"' in allowlist
    assert '"repository-audit-ox6xsu1f"' in allowlist
    assert '"downloads"' not in allowlist
    assert '"packages"' not in allowlist
    assert '"quarantine"' not in allowlist
    assert '"ignored-task-records"' not in allowlist


def test_cleanup_script_rejects_path_escape_newer_dirs_and_reparse_points() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "OrdinalIgnoreCase.Equals($parent, $cacheRoot)" in source
    assert "$item.LastWriteTime -ge $cutoff" in source
    assert source.count("[IO.FileAttributes]::ReparsePoint") >= 2
    assert "Remove-Item -LiteralPath $path -Recurse -Force" in source
    assert "takeown.exe /F $path /R /D Y /SKIPSL" in source
