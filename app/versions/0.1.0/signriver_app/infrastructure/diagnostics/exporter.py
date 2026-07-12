"""Create a minimal, redacted support archive."""

from __future__ import annotations

import json
import os
import platform
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


class DiagnosticExporter:
    def __init__(self, app_root: Path, data_root: Path) -> None:
        self.app_root = Path(app_root).resolve(strict=False)
        self.data_root = Path(data_root).resolve(strict=False)
        self.user_home = Path.home().resolve(strict=False)

    def export(
        self,
        *,
        app_version: str,
        launcher_version: str,
        settings,
        snapshots,
        log_path: Path,
    ) -> Path:
        output_dir = self.data_root / "diagnostics"
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = output_dir / f"signriver-diagnostics-{timestamp}.zip"
        tasks = [{
            "task_id": item.spec.task_id,
            "filename": item.spec.filename,
            "state": item.state.value,
            "bytes_downloaded": item.bytes_downloaded,
            "total_bytes": item.total_bytes,
            "attempt": item.attempt,
            "error": self.sanitize(item.error or "") or None,
        } for item in snapshots]
        report = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "application": {
                "app_version": app_version,
                "launcher_version": launcher_version,
                "python": platform.python_version(),
                "os": platform.system(),
                "os_release": platform.release(),
            },
            "settings": {
                "download_concurrency": settings.download_concurrency,
                "bandwidth_limit_kib": settings.bandwidth_limit_kib,
            },
            "tasks": tasks,
        }
        log_content = ""
        try:
            raw = Path(log_path).read_bytes()[-1024 * 1024:]
            log_content = self.sanitize(raw.decode("utf-8", errors="replace"))
        except OSError:
            log_content = "log file unavailable"
        temporary = output.with_suffix(".zip.tmp")
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "diagnostic.json",
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            )
            archive.writestr("launcher.log", log_content)
        os.replace(temporary, output)
        return output

    def sanitize(self, text: str) -> str:
        result = text.replace(str(self.user_home), "<USER_HOME>")
        result = result.replace(str(self.app_root), "<APP_ROOT>")
        result = re.sub(
            r"(?i)\b(authorization|token|password|cookie)\s*[:=]\s*[^\s,;]+",
            lambda match: match.group(1) + "=<REDACTED>",
            result,
        )
        result = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <REDACTED>", result)
        result = re.sub(r"https?://[^\s\]\[<>\"']+", self._sanitize_url, result)
        return result

    @staticmethod
    def _sanitize_url(match) -> str:
        try:
            parsed = urlsplit(match.group(0))
            hostname = parsed.hostname or "invalid-host"
            netloc = hostname + (f":{parsed.port}" if parsed.port else "")
            return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
        except ValueError:
            return "<REDACTED_URL>"
