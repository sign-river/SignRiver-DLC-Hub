from __future__ import annotations

import io

import pytest

from signriver_app.infrastructure.speed_test import measure_download_speed


class FakeResponse(io.BytesIO):
    def geturl(self) -> str:
        return "https://cdn.example.test/test.bin"

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def test_speed_test_streams_file_and_reports_both_units() -> None:
    ticks = iter((10.0, 12.0))
    result = measure_download_speed(
        "https://example.test/test.bin",
        opener=lambda *_args, **_kwargs: FakeResponse(b"x" * 2 * 1024**2),
        clock=lambda: next(ticks),
        chunk_size=2 * 1024**2,
    )

    assert result.bytes_downloaded == 2 * 1024**2
    assert result.elapsed_seconds == 2.0
    assert result.mebibytes_per_second == 1.0
    assert result.megabits_per_second == pytest.approx(8.388608)


def test_speed_test_rejects_insecure_url() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        measure_download_speed("http://example.test/test.bin")
