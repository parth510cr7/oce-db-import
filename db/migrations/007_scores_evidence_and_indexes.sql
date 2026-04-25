-- Persist domain rationales/evidence; add safety/perf indexes and checks

alter table scores
  add column if not exists rationale text,
  add column if not exists evidence_spans jsonb not null default '[]'::jsonb,
  add column if not exists scored_by text,
  add column if not exists scored_at timestamptz;

-- Basic sanity checks (Postgres doesn't support IF NOT EXISTS for constraints; use DO blocks)
do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'scores_score_nonneg') then
    alter table scores add constraint scores_score_nonneg check (score_value >= 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'scores_max_positive') then
    alter table scores add constraint scores_max_positive check (max_value > 0);
  end if;
  if not exists (select 1 from pg_constraint where conname = 'scores_score_le_max') then
    alter table scores add constraint scores_score_le_max check (score_value <= max_value);
  end if;
end$$;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'critical_flags_severity_check') then
    alter table critical_flags add constraint critical_flags_severity_check check (severity in ('critical','major','minor'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'critical_flags_confidence_check') then
    alter table critical_flags add constraint critical_flags_confidence_check check (detection_confidence is null or (detection_confidence >= 0 and detection_confidence <= 1));
  end if;
end$$;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'station_runs_pass_fail_check') then
    alter table station_runs add constraint station_runs_pass_fail_check check (pass_fail is null or pass_fail in ('pass','borderline','fail'));
  end if;
end$$;

-- Indexes for runtime/scoring queries
create index if not exists station_events_run_type_idx on station_events(station_run_id, event_type);
create index if not exists critical_flags_gate_idx on critical_flags(station_run_id, severity, detection_confidence);
create index if not exists checklist_marks_gate_idx on checklist_marks(station_run_id, mark_value);

-- Prefix lookups for facts
create index if not exists case_history_facts_prefix_idx on case_history_facts(case_id, key text_pattern_ops);
create index if not exists case_exam_findings_prefix_idx on case_exam_findings(case_id, key text_pattern_ops);
create index if not exists case_investigations_prefix_idx on case_investigations(case_id, key text_pattern_ops);

