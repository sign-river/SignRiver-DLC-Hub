from pathlib import Path

from signriver_app.infrastructure.cache import CacheMaintenance


def test_usage_counts_only_runtime_cache_namespaces_and_module_updates(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "cache"
    included = {
        cache / "downloads" / "active.part": b"part",
        cache / "packages" / ("a" * 64) / "dlc.zip": b"package",
        cache / "quarantine" / "broken.bad": b"bad",
        cache / "module-0.2.0-example.zip.part": b"update",
        cache / "module-0.1.9-example.zip": b"archive",
    }
    excluded = {
        cache / "pytest-old-run" / "fixture.bin": b"test artifact",
        cache / "ignored-task-records" / "task.ignored": b"metadata",
        cache / "dlc-catalog.draft.json": b"legacy draft",
    }
    for path, content in {**included, **excluded}.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    assert CacheMaintenance(cache).usage_bytes() == sum(map(len, included.values()))


def test_usage_skips_files_that_cannot_be_inspected(
    tmp_path: Path, monkeypatch,
) -> None:
    cache = tmp_path / "cache"
    readable = cache / "packages" / ("a" * 64) / "readable.zip"
    blocked = cache / "packages" / ("b" * 64) / "blocked.zip"
    readable.parent.mkdir(parents=True)
    blocked.parent.mkdir(parents=True)
    readable.write_bytes(b"readable")
    blocked.write_bytes(b"blocked")
    maintenance = CacheMaintenance(cache)

    original_stat = Path.stat

    def guarded_stat(path: Path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("test path is inaccessible")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)

    assert maintenance.usage_bytes() == len(b"readable")


def test_cleanup_plan_protects_referenced_packages_and_active_parts(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    kept = cache / "packages" / ("a" * 64) / "kept.zip"
    unused = cache / "packages" / ("b" * 64) / "unused.zip"
    bad = cache / "quarantine" / "bad.bin"
    active = cache / "downloads" / "active.part"
    stale = cache / "downloads" / "stale.part"
    for path, content in ((kept, b"keep"), (unused, b"unused"), (bad, b"bad"), (active, b"active"), (stale, b"stale")):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    maintenance = CacheMaintenance(cache)
    plan = maintenance.plan(protected_paths=[kept], active_task_ids=["active"])
    assert kept.parent not in plan.paths
    assert unused.parent in plan.paths
    assert bad in plan.paths
    assert stale in plan.paths
    assert active not in plan.paths
    assert plan.file_count == 3
    maintenance.execute(plan)
    assert kept.exists() and active.exists()
    assert not unused.exists() and not bad.exists() and not stale.exists()


def test_cleanup_rejects_path_outside_cache(tmp_path: Path) -> None:
    from signriver_app.infrastructure.cache import CacheCleanupPlan
    outside = tmp_path / "outside.txt"
    outside.write_text("keep", encoding="utf-8")
    maintenance = CacheMaintenance(tmp_path / "cache")
    try:
        maintenance.execute(CacheCleanupPlan((outside,), 4, 1))
    except ValueError as error:
        assert "escaped" in str(error)
    else:
        raise AssertionError("outside cleanup path was accepted")
    assert outside.exists()
