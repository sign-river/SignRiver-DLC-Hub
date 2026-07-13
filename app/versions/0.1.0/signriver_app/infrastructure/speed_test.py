"""Small streaming download speed test used by the settings page."""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class SpeedTestResult:
    bytes_downloaded: int
    elapsed_seconds: float

    @property
    def mebibytes_per_second(self) -> float:
        return self.bytes_downloaded / self.elapsed_seconds / 1024**2

    @property
    def megabits_per_second(self) -> float:
        return self.bytes_downloaded * 8 / self.elapsed_seconds / 1_000_000


def measure_download_speed(
    url: str,
    *,
    opener=urlopen,
    clock=time.monotonic,
    timeout: float = 20,
    sample_seconds: float = 12,
    max_bytes: int = 64 * 1024**2,
    chunk_size: int = 256 * 1024,
) -> SpeedTestResult:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("speed test URL must use HTTPS")
    if sample_seconds <= 0 or max_bytes < 1 or chunk_size < 1:
        raise ValueError("invalid speed test limits")
    request = Request(
        url,
        headers={"Accept": "application/octet-stream", "User-Agent": "SignRiver-DLC-Hub/0.1"},
    )
    started = clock()
    finished = started
    downloaded = 0
    with opener(request, timeout=timeout) as response:
        final = urlparse(response.geturl())
        if final.scheme != "https":
            raise ValueError("speed test redirected to a non-HTTPS URL")
        while True:
            block = response.read(chunk_size)
            if not block:
                break
            downloaded += len(block)
            finished = clock()
            if downloaded >= max_bytes or finished - started >= sample_seconds:
                break
    elapsed = max(finished - started, 1e-6)
    if downloaded == 0:
        raise ValueError("speed test returned an empty file")
    return SpeedTestResult(downloaded, elapsed)
