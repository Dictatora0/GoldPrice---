from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Optional


def _now() -> datetime:
    return datetime.now()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def _age_seconds(value: Optional[datetime], now: datetime) -> Optional[int]:
    if value is None:
        return None
    seconds = int((now - value).total_seconds())
    return max(seconds, 0)


class RuntimeState:
    """In-process runtime status for daemon health visibility."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._state = {}
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self._state = {
                "app_started_at": None,
                "scheduler": {
                    "enabled": True,
                    "running": False,
                    "started_at": None,
                    "stopped_at": None,
                    "last_error": None,
                    "collect": {
                        "runs_total": 0,
                        "success_total": 0,
                        "failure_total": 0,
                        "rejected_total": 0,
                        "last_started_at": None,
                        "last_completed_at": None,
                        "last_success_at": None,
                        "last_failure_at": None,
                        "last_error": None,
                    },
                },
                "alerts_loop": {
                    "enabled": True,
                    "running": False,
                    "started_at": None,
                    "stopped_at": None,
                    "iterations_total": 0,
                    "last_started_at": None,
                    "last_success_at": None,
                    "last_failure_at": None,
                    "last_error": None,
                },
                "metrics_loop": {
                    "enabled": False,
                    "running": False,
                    "started_at": None,
                    "stopped_at": None,
                    "iterations_total": 0,
                    "last_started_at": None,
                    "last_success_at": None,
                    "last_failure_at": None,
                    "last_error": None,
                },
            }

    def mark_app_started(self) -> None:
        with self._lock:
            self._state["app_started_at"] = _now()

    def set_scheduler_state(
        self,
        *,
        enabled: bool,
        running: bool,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            scheduler = self._state["scheduler"]
            scheduler["enabled"] = bool(enabled)
            scheduler["running"] = bool(running)
            now = _now()
            if running:
                scheduler["started_at"] = now
                scheduler["stopped_at"] = None
            else:
                scheduler["stopped_at"] = now
            if error:
                scheduler["last_error"] = str(error)

    def mark_collection_started(self) -> None:
        with self._lock:
            collect = self._state["scheduler"]["collect"]
            collect["runs_total"] += 1
            collect["last_started_at"] = _now()

    def mark_collection_success(self) -> None:
        with self._lock:
            collect = self._state["scheduler"]["collect"]
            now = _now()
            collect["success_total"] += 1
            collect["last_success_at"] = now
            collect["last_completed_at"] = now
            collect["last_error"] = None

    def mark_collection_rejected(self, reason: str) -> None:
        with self._lock:
            collect = self._state["scheduler"]["collect"]
            now = _now()
            collect["rejected_total"] += 1
            collect["failure_total"] += 1
            collect["last_failure_at"] = now
            collect["last_completed_at"] = now
            collect["last_error"] = str(reason)

    def mark_collection_failure(self, error: str) -> None:
        with self._lock:
            collect = self._state["scheduler"]["collect"]
            now = _now()
            collect["failure_total"] += 1
            collect["last_failure_at"] = now
            collect["last_completed_at"] = now
            collect["last_error"] = str(error)

    def set_loop_enabled(self, loop_name: str, enabled: bool) -> None:
        with self._lock:
            if loop_name in self._state:
                self._state[loop_name]["enabled"] = bool(enabled)

    def mark_loop_running(self, loop_name: str, running: bool) -> None:
        with self._lock:
            loop = self._state.get(loop_name)
            if not loop:
                return
            loop["running"] = bool(running)
            now = _now()
            if running:
                loop["started_at"] = now
                loop["stopped_at"] = None
            else:
                loop["stopped_at"] = now

    def mark_loop_iteration_started(self, loop_name: str) -> None:
        with self._lock:
            loop = self._state.get(loop_name)
            if not loop:
                return
            loop["iterations_total"] += 1
            loop["last_started_at"] = _now()

    def mark_loop_iteration_success(self, loop_name: str) -> None:
        with self._lock:
            loop = self._state.get(loop_name)
            if not loop:
                return
            loop["last_success_at"] = _now()
            loop["last_error"] = None

    def mark_loop_iteration_failure(self, loop_name: str, error: str) -> None:
        with self._lock:
            loop = self._state.get(loop_name)
            if not loop:
                return
            now = _now()
            loop["last_failure_at"] = now
            loop["last_error"] = str(error)

    def snapshot(self) -> dict:
        with self._lock:
            now = _now()
            scheduler = self._state["scheduler"]
            collect = scheduler["collect"]

            scheduler_payload = {
                "enabled": bool(scheduler["enabled"]),
                "running": bool(scheduler["running"]),
                "started_at": _iso(scheduler["started_at"]),
                "stopped_at": _iso(scheduler["stopped_at"]),
                "last_error": scheduler["last_error"],
                "collect": {
                    "runs_total": int(collect["runs_total"]),
                    "success_total": int(collect["success_total"]),
                    "failure_total": int(collect["failure_total"]),
                    "rejected_total": int(collect["rejected_total"]),
                    "last_started_at": _iso(collect["last_started_at"]),
                    "last_completed_at": _iso(collect["last_completed_at"]),
                    "last_success_at": _iso(collect["last_success_at"]),
                    "last_failure_at": _iso(collect["last_failure_at"]),
                    "last_error": collect["last_error"],
                    "last_success_age_seconds": _age_seconds(collect["last_success_at"], now),
                },
            }

            loop_payload = {}
            for name in ("alerts_loop", "metrics_loop"):
                loop = self._state[name]
                loop_payload[name] = {
                    "enabled": bool(loop["enabled"]),
                    "running": bool(loop["running"]),
                    "started_at": _iso(loop["started_at"]),
                    "stopped_at": _iso(loop["stopped_at"]),
                    "iterations_total": int(loop["iterations_total"]),
                    "last_started_at": _iso(loop["last_started_at"]),
                    "last_success_at": _iso(loop["last_success_at"]),
                    "last_failure_at": _iso(loop["last_failure_at"]),
                    "last_error": loop["last_error"],
                    "last_success_age_seconds": _age_seconds(loop["last_success_at"], now),
                }

            return {
                "app_started_at": _iso(self._state["app_started_at"]),
                "scheduler": scheduler_payload,
                "alerts_loop": loop_payload["alerts_loop"],
                "metrics_loop": loop_payload["metrics_loop"],
            }


runtime_state = RuntimeState()
