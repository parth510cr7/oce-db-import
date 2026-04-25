from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json


@dataclass(frozen=True)
class PassFailConfig:
    # numeric thresholds
    pass_percentage: float = 60.0
    borderline_percentage: float = 55.0

    # checklist gating
    fail_if_any_critical_checklist_missed: bool = True

    # safety gating
    fail_if_any_critical_flag: bool = True
    critical_flag_confidence_threshold: float = 0.85

    # domain minimums: require certain domains above thresholds (percent)
    # example: {"safety": 70, "physio_expertise": 60}
    domain_minimums: Optional[Dict[str, float]] = None


def require_database_url() -> str:
    import os

    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    return url


def connect() -> psycopg.Connection:
    return psycopg.connect(require_database_url(), row_factory=dict_row)


def _compute_weighted_domain_percentage(
    conn: psycopg.Connection,
    *,
    attempt_id: str,
    rubric_set_id: str,
) -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """
    Returns (total_score, total_max, percentage, per_domain_rows).
    Uses `scores.weight_applied` if present; else rubric_domains.default_weight; else 1.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            select
              rd.key as domain_key,
              s.score_value::numeric as score_value,
              s.max_value::numeric as max_value,
              coalesce(s.weight_applied, rd.default_weight, 1)::numeric as weight
            from scores s
            join rubric_domains rd on rd.id = s.rubric_domain_id
            where s.attempt_id = %s
              and rd.rubric_set_id = %s
            order by rd.key asc
            """,
            (attempt_id, rubric_set_id),
        )
        rows = cur.fetchall()

    total_score = 0.0
    total_max = 0.0
    per_domain: List[Dict[str, Any]] = []

    for r in rows:
        sv = float(r["score_value"])
        mv = float(r["max_value"])
        w = float(r["weight"])
        total_score += sv * w
        total_max += mv * w
        per_domain.append({"domain_key": r["domain_key"], "score_value": sv, "max_value": mv, "weight": w})

    percentage = (total_score / total_max * 100.0) if total_max > 0 else 0.0
    return total_score, total_max, percentage, per_domain


def _has_failing_critical_checklist(conn: psycopg.Connection, *, station_run_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1
            from checklist_marks cm
            join checklist_items ci on ci.id = cm.checklist_item_id
            where cm.station_run_id = %s
              and ci.is_critical = true
              and cm.mark_value < 1
            limit 1
            """,
            (station_run_id,),
        )
        return cur.fetchone() is not None


def _has_failing_critical_flag(conn: psycopg.Connection, *, station_run_id: str, confidence_threshold: float) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            select 1
            from critical_flags
            where station_run_id = %s
              and severity = 'critical'
              and coalesce(detection_confidence, 0) >= %s
            limit 1
            """,
            (station_run_id, confidence_threshold),
        )
        return cur.fetchone() is not None


def _domain_percentages(per_domain: List[Dict[str, Any]]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for d in per_domain:
        mv = float(d["max_value"])
        sv = float(d["score_value"])
        out[str(d["domain_key"])] = (sv / mv * 100.0) if mv > 0 else 0.0
    return out


def _load_passfail_config_from_exam_station_rules(rules_json: Any) -> Optional[PassFailConfig]:
    """
    Reads `exam_stations.rules_json.passfail` if present, otherwise returns None.
    This keeps backward compatibility: no rules_json => default PassFailConfig().
    """
    if not isinstance(rules_json, dict):
        return None
    pf = rules_json.get("passfail")
    if not isinstance(pf, dict):
        return None

    return PassFailConfig(
        pass_percentage=float(pf.get("pass_percentage", 60.0)),
        borderline_percentage=float(pf.get("borderline_percentage", 55.0)),
        fail_if_any_critical_checklist_missed=bool(pf.get("fail_if_any_critical_checklist_missed", True)),
        fail_if_any_critical_flag=bool(pf.get("fail_if_any_critical_flag", True)),
        critical_flag_confidence_threshold=float(pf.get("critical_flag_confidence_threshold", 0.85)),
        domain_minimums=pf.get("domain_minimums"),
    )


def _fetch_exam_station_rules_json(conn: psycopg.Connection, *, station_run_id: str) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select es.rules_json
            from station_runs sr
            join exam_stations es on es.id = sr.exam_station_id
            where sr.id = %s
            """,
            (station_run_id,),
        )
        row = cur.fetchone()
        if not row or row["rules_json"] is None:
            return {}
        return row["rules_json"]


def compute_and_persist_station_result(
    conn: psycopg.Connection,
    *,
    station_run_id: str,
    attempt_id: str,
    case_id: str,
    rubric_set_id: str,
    config: Optional[PassFailConfig] = None,
) -> Dict[str, Any]:
    # If caller provides config, use it. Otherwise try station rules_json.passfail, else defaults.
    cfg = config
    rules_json = {}
    if cfg is None:
        rules_json = _fetch_exam_station_rules_json(conn, station_run_id=station_run_id)
        cfg = _load_passfail_config_from_exam_station_rules(rules_json) or PassFailConfig()

    total_score, total_max, percentage, per_domain = _compute_weighted_domain_percentage(
        conn, attempt_id=attempt_id, rubric_set_id=rubric_set_id
    )

    fail_reasons: List[str] = []

    if cfg.fail_if_any_critical_flag and _has_failing_critical_flag(
        conn, station_run_id=station_run_id, confidence_threshold=cfg.critical_flag_confidence_threshold
    ):
        fail_reasons.append("critical_flag")

    if cfg.fail_if_any_critical_checklist_missed and _has_failing_critical_checklist(conn, station_run_id=station_run_id):
        fail_reasons.append("critical_checklist_missed")

    # Domain minimums (hard fail)
    if cfg.domain_minimums:
        dp = _domain_percentages(per_domain)
        for domain_key, min_pct in cfg.domain_minimums.items():
            if float(dp.get(domain_key, 0.0)) < float(min_pct):
                fail_reasons.append(f"domain_minimum_not_met:{domain_key}")

    if fail_reasons:
        pass_fail = "fail"
    else:
        if percentage >= cfg.pass_percentage:
            pass_fail = "pass"
        elif percentage >= cfg.borderline_percentage:
            pass_fail = "borderline"
        else:
            pass_fail = "fail"

    result = {
        "station_run_id": station_run_id,
        "attempt_id": attempt_id,
        "case_id": case_id,
        "rubric_set_id": rubric_set_id,
        "total_score": total_score,
        "total_max": total_max,
        "percentage": percentage,
        "pass_fail": pass_fail,
        "fail_reasons": fail_reasons,
        "per_domain": per_domain,
        "config": cfg.__dict__,
        "rules_json_used": rules_json or None,
    }

    with conn.cursor() as cur:
        cur.execute(
            """
            update station_runs
            set pass_fail = %s,
                total_score = %s,
                total_max = %s,
                percentage = %s,
                result_json = %s,
                computed_at = now()
            where id = %s
            """,
            (pass_fail, total_score, total_max, percentage, Json(result), station_run_id),
        )
        cur.execute(
            """
            insert into station_events(station_run_id, event_type, payload_json)
            values (%s, 'result_computed', %s)
            """,
            (station_run_id, Json({"pass_fail": pass_fail, "percentage": percentage, "fail_reasons": fail_reasons})),
        )

    return result

