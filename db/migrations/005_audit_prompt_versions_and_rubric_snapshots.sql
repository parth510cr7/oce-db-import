-- Auditability: prompt versioning, info release logging helpers, rubric snapshots

alter table cases
  add column if not exists prompt_version text not null default 'v1',
  add column if not exists rubric_set_id uuid references rubric_sets(id) on delete set null;

-- Snapshot of the rubric and rules actually applied during an attempt (for reproducible scoring)
alter table attempts
  add column if not exists rubric_snapshot jsonb not null default '{}'::jsonb,
  add column if not exists scoring_rules_snapshot jsonb not null default '{}'::jsonb;

