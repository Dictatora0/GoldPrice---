from app.monitoring.health import build_health_payload
from app.monitoring.runtime_state import runtime_state


def test_runtime_health_degraded_when_scheduler_not_running():
    runtime_state.reset()
    runtime_state.set_scheduler_state(enabled=True, running=False, error="not started")
    runtime_state.mark_loop_running("alerts_loop", True)

    payload = build_health_payload()

    assert payload["runtime"]["ok"] is False
    assert payload["runtime"]["scheduler"]["ok"] is False
    assert payload["status"] == "degraded"


def test_runtime_health_ok_when_scheduler_and_alert_loop_running():
    runtime_state.reset()
    runtime_state.set_scheduler_state(enabled=True, running=True)
    runtime_state.mark_loop_running("alerts_loop", True)
    runtime_state.mark_collection_started()
    runtime_state.mark_collection_success()
    runtime_state.mark_loop_iteration_started("alerts_loop")
    runtime_state.mark_loop_iteration_success("alerts_loop")

    payload = build_health_payload()

    assert payload["runtime"]["scheduler"]["running"] is True
    assert payload["runtime"]["alerts_loop"]["running"] is True
    assert payload["runtime"]["details"]["scheduler"]["collect"]["success_total"] >= 1
