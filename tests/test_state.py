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
