from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class EffectiveStationConfig:
    reading_seconds: int
    active_seconds: int
    probe_budget: int
    no_backtracking: bool
    strict_actions: bool
    max_fact_prefix_results: int = 10
    warning_thresholds_s: Tuple[int, ...] = (120, 60, 30, 10)


def effective_config_from_row(row: Dict[str, Any]) -> EffectiveStationConfig:
    # Precedence: exam_stations overrides case defaults when present.
    reading = int(row.get("es_reading_seconds") or row.get("c_reading_seconds") or 60)
    active = int(row.get("es_active_seconds") or row.get("c_time_limit_seconds") or 480)
    probe_budget = int(row.get("es_probe_budget") or row.get("c_probe_budget") or 0)

    no_backtracking = False
    strict_actions = False
    max_fact_prefix_results = 10

    rules = row.get("es_rules_json") or {}
    if isinstance(rules, dict):
        no_backtracking = bool(rules.get("no_backtracking", False))
        strict_actions = bool(rules.get("strict_actions", False))
        try:
            max_fact_prefix_results = int(rules.get("max_fact_prefix_results", max_fact_prefix_results))
        except Exception:
            pass

    exam_mode = row.get("c_exam_mode") or {}
    if isinstance(exam_mode, dict):
        no_backtracking = bool(exam_mode.get("no_backtracking", no_backtracking))
        strict_actions = bool(exam_mode.get("strict_actions", strict_actions))
        try:
            max_fact_prefix_results = int(exam_mode.get("max_fact_prefix_results", max_fact_prefix_results))
        except Exception:
            pass

    thresholds = (120, 60, 30, 10)
    timing = rules.get("timing") if isinstance(rules, dict) else None
    if isinstance(timing, dict) and isinstance(timing.get("warning_thresholds_s"), list):
        vals = []
        for v in timing["warning_thresholds_s"]:
            try:
                vals.append(int(v))
            except Exception:
                continue
        if vals:
            thresholds = tuple(sorted(set(vals), reverse=True))

    return EffectiveStationConfig(
        reading_seconds=reading,
        active_seconds=active,
        probe_budget=probe_budget,
        no_backtracking=no_backtracking,
        strict_actions=strict_actions,
        max_fact_prefix_results=max_fact_prefix_results,
        warning_thresholds_s=thresholds,
    )

