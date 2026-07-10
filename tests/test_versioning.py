import pytest

from signriver_launcher.versioning import Version


def test_semantic_version_ordering() -> None:
    versions = [
        Version.parse("1.0.0"),
        Version.parse("1.0.0-beta.11"),
        Version.parse("1.0.0-alpha"),
        Version.parse("1.0.0-beta.2"),
        Version.parse("1.0.1"),
    ]
    assert sorted(versions) == [
        Version.parse("1.0.0-alpha"),
        Version.parse("1.0.0-beta.2"),
        Version.parse("1.0.0-beta.11"),
        Version.parse("1.0.0"),
        Version.parse("1.0.1"),
    ]


@pytest.mark.parametrize("value", ["1", "1.2", "01.2.3", "v1.2.3", "1.2.3.4"])
def test_rejects_invalid_versions(value: str) -> None:
    with pytest.raises(ValueError):
        Version.parse(value)
