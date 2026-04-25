-- OSCE runtime primitives: exams/stations, station runs/events,
-- checklist marking, global ratings, and safety/critical flags.

-- Exam container (optional but enables circuits)
create table if not exists exams (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  version text not null,
  active boolean not null default false,
  created_at timestamptz not null default now(),
  unique (name, version)
);

create table if not exists exam_stations (
  id uuid primary key default gen_random_uuid(),
  exam_id uuid not null references exams(id) on delete cascade,
  order_index integer not null,
  case_id uuid not null references cases(id) on delete cascade,
  reading_seconds integer not null default 60,
  active_seconds integer not null default 480,
  transition_seconds integer not null default 0,
  probe_budget integer not null default 0,
  rules_json jsonb not null default '{}'::jsonb,
  unique (exam_id, order_index)
);

-- Station run is the runtime state machine for an attempt on a station/case
create table if not exists station_runs (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references attempts(id) on delete cascade,
  exam_station_id uuid references exam_stations(id) on delete set null,
  state text not null default 'reading', -- reading/active/closing/completed
  started_at timestamptz not null default now(),
  ended_at timestamptz,
  current_prompt_order_index integer not null default 0,
  locked_at timestamptz,
  unique (attempt_id)
);

create table if not exists station_events (
  id uuid primary key default gen_random_uuid(),
  station_run_id uuid not null references station_runs(id) on delete cascade,
  event_type text not null, -- prompt_delivered/response_received/probe_delivered/time_warning/station_locked/station_ended
  at timestamptz not null default now(),
  payload_json jsonb not null default '{}'::jsonb
);

-- Checklist items per case (key features)
create table if not exists checklist_items (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  key text not null,
  text text not null,
  weight numeric not null default 1,
  is_critical boolean not null default false,
  applies_to_prompt_id uuid references case_prompts(id) on delete set null,
  unique (case_id, key)
);

create table if not exists checklist_marks (
  id uuid primary key default gen_random_uuid(),
  station_run_id uuid not null references station_runs(id) on delete cascade,
  checklist_item_id uuid not null references checklist_items(id) on delete cascade,
  mark_value numeric not null, -- 0/1/2 etc
  evidence_spans jsonb not null default '[]'::jsonb,
  unique (station_run_id, checklist_item_id)
);

-- Global ratings (in addition to domain scores)
create table if not exists global_ratings (
  id uuid primary key default gen_random_uuid(),
  rubric_set_id uuid not null references rubric_sets(id) on delete cascade,
  key text not null,
  display_name text not null,
  anchors jsonb not null,
  unique (rubric_set_id, key)
);

create table if not exists global_rating_marks (
  id uuid primary key default gen_random_uuid(),
  station_run_id uuid not null references station_runs(id) on delete cascade,
  global_rating_id uuid not null references global_ratings(id) on delete cascade,
  score_value numeric not null,
  max_value numeric not null,
  rationale text,
  evidence_spans jsonb not null default '[]'::jsonb,
  unique (station_run_id, global_rating_id)
);

-- Safety/critical flags (commission, omission, delay, contraindication)
create table if not exists critical_flags (
  id uuid primary key default gen_random_uuid(),
  station_run_id uuid not null references station_runs(id) on delete cascade,
  flag_key text not null,
  severity text not null, -- critical/major/minor
  description text not null,
  evidence_spans jsonb not null default '[]'::jsonb,
  detection_confidence numeric,
  created_at timestamptz not null default now()
);

