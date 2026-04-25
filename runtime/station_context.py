from __future__ import annotations

from typing import Any, Dict

import psycopg
from psycopg.rows import dict_row


def load_station_context(conn: psycopg.Connection, *, station_run_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select
              sr.id::text as station_run_id,
              sr.state,
              sr.started_at,
              sr.ended_at,
              sr.locked_at,
              sr.current_prompt_order_index,
              sr.attempt_id::text as attempt_id,
              a.case_id::text as case_id,
              sr.exam_station_id::text as exam_station_id,
              es.reading_seconds as es_reading_seconds,
              es.active_seconds as es_active_seconds,
              es.probe_budget as es_probe_budget,
              es.rules_json as es_rules_json,
              c.reading_seconds as c_reading_seconds,
              c.time_limit_seconds as c_time_limit_seconds,
              c.probe_budget as c_probe_budget,
              c.exam_mode as c_exam_mode,
              c.allowed_actions as c_allowed_actions
            from station_runs sr
            join attempts a on a.id = sr.attempt_id
            join cases c on c.id = a.case_id
            left join exam_stations es on es.id = sr.exam_station_id
            where sr.id = %s
            """,
            (station_run_id,),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError(f"station_run not found: {station_run_id}")
        return row

