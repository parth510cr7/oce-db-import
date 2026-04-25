-- Persist computed station results (pass/fail, totals) for deterministic UX

alter table station_runs
  add column if not exists pass_fail text, -- pass|borderline|fail
  add column if not exists total_score numeric,
  add column if not exists total_max numeric,
  add column if not exists percentage numeric,
  add column if not exists result_json jsonb not null default '{}'::jsonb,
  add column if not exists computed_at timestamptz;

