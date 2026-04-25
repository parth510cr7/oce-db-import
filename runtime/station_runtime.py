from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from runtime.action_taxonomy import is_known_action_key, normalize_allowed_actions
from runtime.events import emit_event
from runtime.station_context import load_station_context
from runtime.config import effective_config_from_row


def require_database_url() -> str:
    from runtime.dbconn import require_database_url as _r

    return _r()


def connect() -> psycopg.Connection:
    from runtime.dbconn import connect as _c

    return _c()


@dataclass(frozen=True)
class GatedFact:
    kind: str  # history|exam|investigation|initial_vitals|patient_profile
    key: str
    visibility: str  # always|on_request|hidden
    payload: Dict[str, Any]


def ensure_station_run(conn: psycopg.Connection, *, attempt_id: str, exam_station_id: Optional[str] = None) -> str:
    with conn.cursor() as cur:
        cur.execute("select id::text as id from station_runs where attempt_id = %s", (attempt_id,))
        row = cur.fetchone()
        if row:
            return row["id"]
        cur.execute(
            """
            insert into station_runs(attempt_id, exam_station_id, state, current_prompt_order_index)
            values (%s, %s, 'reading', 0)
            returning id::text as id
            """,
            (attempt_id, exam_station_id),
        )
        return cur.fetchone()["id"]


def log_event(conn: psycopg.Connection, *, station_run_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
    # Backward compatible: delegate to normalized emitter; also emits legacy.
    emit_event(conn, station_run_id=station_run_id, event_type=event_type, payload=payload, emit_legacy=True)


def record_action_performed(
    conn: psycopg.Connection,
    *,
    station_run_id: str,
    action_key: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    emit_event(
        conn,
        station_run_id=station_run_id,
        event_type="action.performed",
        payload={"action_key": action_key, **(payload or {})},
        emit_legacy=True,
    )


def _fetch_performed_actions(conn: psycopg.Connection, *, station_run_id: str) -> Set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select payload_json->>'action_key' as action_key
            from station_events
            where station_run_id = %s
              and event_type in ('action.performed', 'action_performed')
            """,
            (station_run_id,),
        )
        return {r["action_key"] for r in cur.fetchall() if r.get("action_key")}


def _allowed_action_keys_from_case(case_allowed_actions: Any) -> Set[str]:
    return normalize_allowed_actions(case_allowed_actions)


def _is_action_allowed(allowed: Set[str], requested_action_key: str) -> bool:
    # 1) deny unknown action keys (prevents string injection / typos)
    if not is_known_action_key(requested_action_key):
        return False
    # 2) if allowlist empty -> permissive for now (practice mode).
    #    Tighten later by making this depend on exam_mode.strict_actions.
    if not allowed:
        return True
    return requested_action_key in allowed


def _strict_actions_enabled(conn: psycopg.Connection, *, station_run_id: str) -> bool:
    row = load_station_context(conn, station_run_id=station_run_id)
    cfg = effective_config_from_row(row)
    return bool(cfg.strict_actions)


def _check_prereqs(performed: Set[str], prereq_actions: Sequence[str]) -> bool:
    return all(a in performed for a in prereq_actions)


def _row_to_fact(kind: str, row: Dict[str, Any]) -> GatedFact:
    if kind == "history":
        payload = row["fact"]
        key = row["key"]
        visibility = row["visibility"]
    elif kind == "exam":
        payload = row["finding"]
        key = row["key"]
        visibility = row["visibility"]
    elif kind == "investigation":
        payload = row["investigation"]
        key = row["key"]
        visibility = row["visibility"]
    else:
        raise ValueError(f"Unknown fact kind: {kind}")
    return GatedFact(kind=kind, key=key, visibility=visibility, payload=payload)


def get_case_context(conn: psycopg.Connection, *, case_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select
              c.id::text as id,
              c.case_type,
              c.allowed_actions,
              c.exam_mode
            from cases c
            where c.id = %s
            """,
            (case_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"Case not found: {case_id}")
        return row


def list_always_visible_facts(conn: psycopg.Connection, *, case_id: str) -> List[GatedFact]:
    out: List[GatedFact] = []
    with conn.cursor() as cur:
        cur.execute(
            "select key, fact, visibility from case_history_facts where case_id = %s and visibility = 'always' order by key",
            (case_id,),
        )
        out.extend([_row_to_fact("history", r) for r in cur.fetchall()])
        cur.execute(
            "select key, finding, visibility from case_exam_findings where case_id = %s and visibility = 'always' order by key",
            (case_id,),
        )
        out.extend([_row_to_fact("exam", r) for r in cur.fetchall()])
        cur.execute(
            "select key, investigation, visibility from case_investigations where case_id = %s and visibility = 'always' order by key",
            (case_id,),
        )
        out.extend([_row_to_fact("investigation", r) for r in cur.fetchall()])
    return out


def request_fact(
    conn: psycopg.Connection,
    *,
    station_run_id: str,
    case_id: str,
    kind: str,  # history|exam|investigation
    key: str,
    requested_action_key: str,
) -> Optional[GatedFact]:
    """
    Enforces:
    - 3-state visibility (always/on_request/hidden)
    - allowed action policy (best-effort; case.allowed_actions currently stores human text)
    - prerequisites stored inside the fact JSON under `prereq_actions`
    Logs station_events:
    - action_denied (if disallowed)
    - fact_revealed (if returned)
    - fact_withheld (if hidden or prereqs missing)
    """
    case_ctx = get_case_context(conn, case_id=case_id)
    allowed = _allowed_action_keys_from_case(case_ctx.get("allowed_actions"))
    strict = _strict_actions_enabled(conn, station_run_id=station_run_id)
    if strict and not allowed:
        emit_event(
            conn,
            station_run_id=station_run_id,
            event_type="action.denied",
            payload={"action_key": requested_action_key, "reason": "strict_actions_empty_allowlist"},
            emit_legacy=True,
        )
        return None
    if not _is_action_allowed(allowed, requested_action_key):
        emit_event(
            conn,
            station_run_id=station_run_id,
            event_type="action.denied",
            payload={"action_key": requested_action_key, "reason": "not_allowed_by_case_or_unknown"},
            emit_legacy=True,
        )
        return None

    performed = _fetch_performed_actions(conn, station_run_id=station_run_id)

    with conn.cursor() as cur:
        if kind == "history":
            cur.execute(
                "select key, fact, visibility from case_history_facts where case_id = %s and key = %s",
                (case_id, key),
            )
        elif kind == "exam":
            cur.execute(
                "select key, finding, visibility from case_exam_findings where case_id = %s and key = %s",
                (case_id, key),
            )
        elif kind == "investigation":
            cur.execute(
                "select key, investigation, visibility from case_investigations where case_id = %s and key = %s",
                (case_id, key),
            )
        else:
            raise ValueError(f"Unknown kind: {kind}")

        row = cur.fetchone()
        if not row:
            emit_event(conn, station_run_id=station_run_id, event_type="fact.withheld", payload={"kind": kind, "key": key, "reason": "not_found"}, emit_legacy=True)
            return None

        fact = _row_to_fact(kind, row)
        if fact.visibility == "hidden":
            emit_event(conn, station_run_id=station_run_id, event_type="fact.withheld", payload={"kind": kind, "key": key, "reason": "hidden"}, emit_legacy=True)
            return None

        prereq_actions = []
        if isinstance(fact.payload, dict):
            prereq_actions = fact.payload.get("prereq_actions") or []
        if prereq_actions and isinstance(prereq_actions, list):
            prereq_actions = [str(a) for a in prereq_actions]
        else:
            prereq_actions = []

        if prereq_actions and not _check_prereqs(performed, prereq_actions):
            emit_event(
                conn,
                station_run_id=station_run_id,
                event_type="fact.withheld",
                payload={"kind": kind, "key": key, "reason": "missing_prereqs", "prereq_actions": prereq_actions},
                emit_legacy=True,
            )
            return None

        # ok to reveal (always or on_request)
        emit_event(
            conn,
            station_run_id=station_run_id,
            event_type="fact.revealed",
            payload={"kind": kind, "key": key, "visibility": fact.visibility, "action_key": requested_action_key},
            emit_legacy=True,
        )
        return fact


def request_facts_by_prefix(
    conn: psycopg.Connection,
    *,
    station_run_id: str,
    case_id: str,
    kind: str,
    key_prefix: str,
    requested_action_key: str,
    limit: int = 50,
) -> List[GatedFact]:
    # Exam realism: prevent broad "scan the chart" requests.
    row = load_station_context(conn, station_run_id=station_run_id)
    cfg = effective_config_from_row(row)
    strict = bool(cfg.strict_actions)
    max_results = int(cfg.max_fact_prefix_results or 10)

    prefix = (key_prefix or "").strip()
    if strict:
        # Require a meaningful prefix (e.g. "hx.red_flags." not "hx.")
        if len(prefix) < 8 or prefix.endswith(".") is False:
            emit_event(
                conn,
                station_run_id=station_run_id,
                event_type="action.denied",
                payload={"action_key": requested_action_key, "reason": "prefix_too_broad", "key_prefix": prefix},
                emit_legacy=True,
            )
            return []

    with conn.cursor() as cur:
        if kind == "history":
            cur.execute(
                "select key, fact, visibility from case_history_facts where case_id = %s and key like %s order by key limit %s",
                (case_id, f"{prefix}%", min(int(limit), max_results)),
            )
        elif kind == "exam":
            cur.execute(
                "select key, finding, visibility from case_exam_findings where case_id = %s and key like %s order by key limit %s",
                (case_id, f"{prefix}%", min(int(limit), max_results)),
            )
        elif kind == "investigation":
            cur.execute(
                "select key, investigation, visibility from case_investigations where case_id = %s and key like %s order by key limit %s",
                (case_id, f"{prefix}%", min(int(limit), max_results)),
            )
        else:
            raise ValueError(f"Unknown kind: {kind}")

        keys = [r["key"] for r in cur.fetchall()]

    out: List[GatedFact] = []
    for k in keys:
        f = request_fact(conn, station_run_id=station_run_id, case_id=case_id, kind=kind, key=k, requested_action_key=requested_action_key)
        if f:
            out.append(f)
    return out

