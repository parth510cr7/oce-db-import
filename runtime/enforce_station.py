from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import psycopg
from psycopg.rows import dict_row

from runtime.config import EffectiveStationConfig, effective_config_from_row
from runtime.dbconn import require_database_url
from runtime.events import emit_event
from runtime.station_context import load_station_context


def connect() -> psycopg.Connection:
    return psycopg.connect(require_database_url(), row_factory=dict_row)


def _load_station_context(conn: psycopg.Connection, *, station_run_id: str) -> Dict[str, Any]:
    return load_station_context(conn, station_run_id=station_run_id)


def _effective_config(row: Dict[str, Any]) -> EffectiveStationConfig:
    return effective_config_from_row(row)


def _station_elapsed_s(started_at: datetime) -> int:
    now = datetime.now(timezone.utc)
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return int((now - started_at).total_seconds())


def enforce_once(conn: psycopg.Connection, *, station_run_id: str, emit_legacy: bool = True) -> Dict[str, Any]:
    row = _load_station_context(conn, station_run_id=station_run_id)
    cfg = _effective_config(row)

    started_at: datetime = row["started_at"]
    elapsed = _station_elapsed_s(started_at)

    reading_deadline = cfg.reading_seconds
    active_deadline = cfg.reading_seconds + cfg.active_seconds

    # Emit a policy snapshot once per run (idempotent-ish: only if not present)
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1
            from station_events
            where station_run_id = %s and event_type in ('policy.snapshot','policy_snapshot')
            limit 1
            """,
            (station_run_id,),
        )
        has_snapshot = cur.fetchone() is not None
    if not has_snapshot:
        emit_event(
            conn,
            station_run_id=station_run_id,
            event_type="policy.snapshot",
            payload={
                "reading_seconds": cfg.reading_seconds,
                "active_seconds": cfg.active_seconds,
                "probe_budget": cfg.probe_budget,
                "no_backtracking": cfg.no_backtracking,
                "strict_actions": cfg.strict_actions,
                "max_fact_prefix_results": cfg.max_fact_prefix_results,
                "warning_thresholds_s": list(cfg.warning_thresholds_s),
            },
            emit_legacy=emit_legacy,
        )

    # State transitions based on time
    state = row["state"]
    locked_at = row["locked_at"]

    updates: Dict[str, Any] = {"station_run_id": station_run_id, "elapsed_s": elapsed, "state_before": state}

    if state == "reading" and elapsed >= reading_deadline:
        with conn.cursor() as cur:
            cur.execute("update station_runs set state='active' where id=%s", (station_run_id,))
        emit_event(conn, station_run_id=station_run_id, event_type="station.lifecycle.phase_changed", payload={"from": "reading", "to": "active"}, emit_legacy=False)
        state = "active"

    # warnings during active
    if state in ("active", "closing"):
        remaining = max(0, active_deadline - elapsed)
        for t in cfg.warning_thresholds_s:
            # emit threshold events once (dedupe via presence check)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    select 1 from station_events
                    where station_run_id=%s
                      and event_type in ('time.warning','time_warning')
                      and (payload_json->>'threshold_s')::int = %s
                    limit 1
                    """,
                    (station_run_id, int(t)),
                )
                seen = cur.fetchone() is not None
            if not seen and remaining <= t:
                emit_event(
                    conn,
                    station_run_id=station_run_id,
                    event_type="time.warning",
                    payload={"threshold_s": int(t), "remaining_s": int(remaining)},
                    emit_legacy=emit_legacy,
                )

    # lock/end at time expiry
    if locked_at is None and elapsed >= active_deadline:
        with conn.cursor() as cur:
            cur.execute(
                """
                update station_runs
                set locked_at = now(), state='completed', ended_at = now()
                where id = %s
                """,
                (station_run_id,),
            )
        emit_event(conn, station_run_id=station_run_id, event_type="station.lifecycle.locked", payload={"reason": "time_expired"}, emit_legacy=emit_legacy)
        emit_event(conn, station_run_id=station_run_id, event_type="station.lifecycle.ended", payload={"reason": "time_expired"}, emit_legacy=emit_legacy)
        updates["locked"] = True
        state = "completed"

    updates["state_after"] = state
    updates["config"] = cfg.__dict__
    return updates


def main() -> int:
    ap = argparse.ArgumentParser(description="Enforce station timers/budgets from DB state and emit station_events.")
    ap.add_argument("--station-run-id", required=True)
    ap.add_argument("--no-legacy", action="store_true", help="Do not emit legacy event types.")
    args = ap.parse_args()

    with connect() as conn:
        conn.autocommit = True
        result = enforce_once(conn, station_run_id=args.station_run_id, emit_legacy=not args.no_legacy)
        print(result)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

