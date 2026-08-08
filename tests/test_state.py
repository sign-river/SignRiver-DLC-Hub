from signriver_launcher.state import StateStore


def test_activation_health_and_rollback(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.bootstrap("0.1.0")

    pending = store.activate("0.1.1")
    assert pending.active_version == "0.1.1"
    assert pending.previous_version == "0.1.0"
    assert pending.pending_version == "0.1.1"

    rolled_back = store.rollback_pending("0.1.1")
    assert rolled_back.active_version == "0.1.0"
    assert rolled_back.pending_version is None
    assert rolled_back.bad_versions == ["0.1.1"]

    store.activate("0.1.2")
    healthy = store.mark_healthy("0.1.2")
    assert healthy.active_version == "0.1.2"
    assert healthy.pending_version is None

def test_rollback_works_after_module_was_confirmed_healthy(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.bootstrap("0.1.0")
    store.activate("0.1.1")
    store.mark_healthy("0.1.1")

    state = store.load()
    assert state.active_version == "0.1.1"
    assert state.previous_version == "0.1.0"
    assert state.pending_version is None

    rolled_back = store.rollback_pending("0.1.1")
    assert rolled_back.active_version == "0.1.0"
    assert rolled_back.previous_version is None
    assert rolled_back.pending_version is None
    assert rolled_back.bad_versions == ["0.1.1"]


def test_rollback_requires_a_previous_version(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.bootstrap("0.1.0")

    try:
        store.rollback_pending("0.1.0")
    except Exception as error:
        assert "no rollback target" in str(error)
    else:
        raise AssertionError("expected rollback to fail without a previous version")


def test_fallback_to_activates_older_version_and_marks_failed(tmp_path) -> None:
    store = StateStore(tmp_path / "state.json")
    store.bootstrap("0.1.2")

    state = store.fallback_to("0.1.2", "0.1.1")

    assert state.active_version == "0.1.1"
    assert state.previous_version is None
    assert state.pending_version is None
    assert state.bad_versions == ["0.1.2"]
