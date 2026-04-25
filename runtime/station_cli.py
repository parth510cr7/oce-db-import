from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from runtime.enforce_station import connect as connect_db
from runtime.events import emit_event
from runtime.station_runtime import ensure_station_run
from runtime.station_context import load_station_context
from runtime.config import effective_config_from_row
from runtime.action_taxonomy import is_known_action_key


def _require_attempt(conn: psycopg.Connection, attempt_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select a.id::text as attempt_id, a.case_id::text as case_id
            from attempts a
            where a.id = %s
            """,
            (attempt_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"attempt not found: {attempt_id}")
        return row


def station_start(conn: psycopg.Connection, *, attempt_id: str, exam_station_id: Optional[str]) -> str:
    _require_attempt(conn, attempt_id)
    station_run_id = ensure_station_run(conn, attempt_id=attempt_id, exam_station_id=exam_station_id)
    emit_event(conn, station_run_id=station_run_id, event_type="station.lifecycle.started", payload={"attempt_id": attempt_id}, emit_legacy=False)
    # Immediately emit policy snapshot / timing warnings if applicable
    from runtime.enforce_station import enforce_once

    enforce_once(conn, station_run_id=station_run_id, emit_legacy=True)
    return station_run_id


def action_performed(conn: psycopg.Connection, *, station_run_id: str, action_key: str) -> None:
    if not is_known_action_key(action_key):
        emit_event(conn, station_run_id=station_run_id, event_type="action.denied", payload={"action_key": action_key, "reason": "unknown_action_key"})
        raise SystemExit(f"Unknown action_key: {action_key}")
    emit_event(conn, station_run_id=station_run_id, event_type="action.performed", payload={"action_key": action_key})


def probe_request(conn: psycopg.Connection, *, station_run_id: str, kind: str = "clarification") -> Dict[str, Any]:
    row = load_station_context(conn, station_run_id=station_run_id)
    cfg = effective_config_from_row(row)

    with conn.cursor() as cur:
        cur.execute(
            """
            select count(*)::int as used
            from station_events
            where station_run_id = %s
              and event_type in ('probe.decision','probe_decision')
              and (payload_json->>'decision') = 'granted'
            """,
            (station_run_id,),
        )
        used = int(cur.fetchone()["used"])

    emit_event(conn, station_run_id=station_run_id, event_type="probe.requested", payload={"probe_kind": kind, "probe_used_before": used, "probe_budget_total": cfg.probe_budget})

    if cfg.probe_budget <= 0:
        decision = "denied"
        reason = "no_budget_configured"
    elif used >= cfg.probe_budget:
        decision = "denied"
        reason = "budget_exhausted"
    else:
        decision = "granted"
        reason = "within_budget"

    used_after = used + (1 if decision == "granted" else 0)
    emit_event(
        conn,
        station_run_id=station_run_id,
        event_type="probe.decision",
        payload={
            "decision": decision,
            "reason_code": reason,
            "probe_budget_total": cfg.probe_budget,
            "probe_used_before": used,
            "probe_used_after": used_after,
            "probe_remaining_after": max(0, cfg.probe_budget - used_after),
        },
    )
    return {"decision": decision, "reason_code": reason, "probe_budget_total": cfg.probe_budget, "probe_used_after": used_after}


def navigate(conn: psycopg.Connection, *, station_run_id: str, to_order_index: int, action: str = "go_to_prompt") -> Dict[str, Any]:
    row = load_station_context(conn, station_run_id=station_run_id)
    cfg = effective_config_from_row(row)
    from_idx = int(row["current_prompt_order_index"] or 0)

    emit_event(
        conn,
        station_run_id=station_run_id,
        event_type="navigation.requested",
        payload={"from_order_index": from_idx, "to_order_index": int(to_order_index), "action": action},
    )

    if cfg.no_backtracking and int(to_order_index) < from_idx:
        emit_event(
            conn,
            station_run_id=station_run_id,
            event_type="navigation.decision",
            payload={"decision": "denied", "reason_code": "no_backtracking_enabled", "effective_current_prompt_order_index": from_idx},
        )
        return {"decision": "denied", "reason_code": "no_backtracking_enabled", "effective_current_prompt_order_index": from_idx}

    # granted
    with conn.cursor() as cur:
        cur.execute("update station_runs set current_prompt_order_index=%s where id=%s", (int(to_order_index), station_run_id))
    emit_event(
        conn,
        station_run_id=station_run_id,
        event_type="navigation.decision",
        payload={"decision": "granted", "reason_code": "same_or_forward", "effective_current_prompt_order_index": int(to_order_index)},
    )
    return {"decision": "granted", "effective_current_prompt_order_index": int(to_order_index)}


def prompt_delivered(conn: psycopg.Connection, *, station_run_id: str, prompt_id: str, order_index: int, prompt_type: str) -> None:
    emit_event(
        conn,
        station_run_id=station_run_id,
        event_type="prompt.delivered",
        payload={"prompt_id": prompt_id, "order_index": int(order_index), "prompt_type": prompt_type},
    )
    with conn.cursor() as cur:
        cur.execute(
            "update station_runs set current_prompt_order_index=%s where id=%s",
            (int(order_index), station_run_id),
        )


def response_received(conn: psycopg.Connection, *, station_run_id: str, attempt_id: str, prompt_id: str, response_text: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into responses(attempt_id, prompt_id, response_text)
            values (%s, %s, %s)
            on conflict (attempt_id, prompt_id) do update
              set response_text = excluded.response_text,
                  responded_at = now()
            returning id::text as id
            """,
            (attempt_id, prompt_id, response_text),
        )
        response_id = cur.fetchone()["id"]

    emit_event(
        conn,
        station_run_id=station_run_id,
        event_type="response.received",
        payload={"prompt_id": prompt_id, "response_id": response_id, "modality": "text", "text_len": len(response_text or "")},
    )
    return response_id


def main() -> int:
    ap = argparse.ArgumentParser(description="Station runtime helpers (start station, log prompts/responses/actions).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s_start = sub.add_parser("start")
    s_start.add_argument("--attempt-id", required=True)
    s_start.add_argument("--exam-station-id", default=None)

    s_action = sub.add_parser("action")
    s_action.add_argument("--station-run-id", required=True)
    s_action.add_argument("--action-key", required=True)

    s_prompt = sub.add_parser("prompt-delivered")
    s_prompt.add_argument("--station-run-id", required=True)
    s_prompt.add_argument("--prompt-id", required=True)
    s_prompt.add_argument("--order-index", type=int, required=True)
    s_prompt.add_argument("--prompt-type", required=True)

    s_resp = sub.add_parser("response")
    s_resp.add_argument("--station-run-id", required=True)
    s_resp.add_argument("--attempt-id", required=True)
    s_resp.add_argument("--prompt-id", required=True)
    s_resp.add_argument("--text", required=True)

    s_probe = sub.add_parser("probe-request")
    s_probe.add_argument("--station-run-id", required=True)
    s_probe.add_argument("--kind", default="clarification")

    s_nav = sub.add_parser("navigate")
    s_nav.add_argument("--station-run-id", required=True)
    s_nav.add_argument("--to-order-index", type=int, required=True)
    s_nav.add_argument("--action", default="go_to_prompt")

    args = ap.parse_args()

    with connect_db() as conn:
        conn.autocommit = True
        if args.cmd == "start":
            srid = station_start(conn, attempt_id=args.attempt_id, exam_station_id=args.exam_station_id)
            print({"station_run_id": srid})
        elif args.cmd == "action":
            action_performed(conn, station_run_id=args.station_run_id, action_key=args.action_key)
            print({"ok": True})
        elif args.cmd == "prompt-delivered":
            prompt_delivered(
                conn,
                station_run_id=args.station_run_id,
                prompt_id=args.prompt_id,
                order_index=args.order_index,
                prompt_type=args.prompt_type,
            )
            print({"ok": True})
        elif args.cmd == "response":
            rid = response_received(
                conn,
                station_run_id=args.station_run_id,
                attempt_id=args.attempt_id,
                prompt_id=args.prompt_id,
                response_text=args.text,
            )
            print({"response_id": rid})
        elif args.cmd == "probe-request":
            print(probe_request(conn, station_run_id=args.station_run_id, kind=args.kind))
        elif args.cmd == "navigate":
            print(navigate(conn, station_run_id=args.station_run_id, to_order_index=args.to_order_index, action=args.action))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

