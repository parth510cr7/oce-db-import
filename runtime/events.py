from __future__ import annotations

from typing import Any, Dict, Optional

import psycopg
from psycopg.types.json import Json


# Backward-compatible mapping: we now emit normalized dot-namespaced types.
# We optionally also emit legacy types for older consumers.
LEGACY_EVENT_MAP: Dict[str, str] = {
    "action.performed": "action_performed",
    "action.denied": "action_denied",
    "fact.revealed": "fact_revealed",
    "fact.withheld": "fact_withheld",
    "prompt.delivered": "prompt_delivered",
    "response.received": "response_received",
    "time.warning": "time_warning",
    "station.lifecycle.locked": "station_locked",
    "station.lifecycle.ended": "station_ended",
    "scoring.result_computed": "result_computed",
    "policy.snapshot": "policy_snapshot",
    "probe.requested": "probe_requested",
    "probe.decision": "probe_decision",
    "navigation.requested": "navigation_requested",
    "navigation.decision": "navigation_decision",
}


def emit_event(
    conn: psycopg.Connection,
    *,
    station_run_id: str,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
    emit_legacy: bool = True,
) -> None:
    """
    Append-only event writer.

    - Emits normalized event types (dot names)
    - Optionally also emits the legacy event type for backward compatibility
    """
    p = payload or {}
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into station_events(station_run_id, event_type, payload_json)
            values (%s, %s, %s)
            """,
            (station_run_id, event_type, Json(p)),
        )

        legacy = LEGACY_EVENT_MAP.get(event_type)
        if emit_legacy and legacy and legacy != event_type:
            cur.execute(
                """
                insert into station_events(station_run_id, event_type, payload_json)
                values (%s, %s, %s)
                """,
                (station_run_id, legacy, Json(p)),
            )

