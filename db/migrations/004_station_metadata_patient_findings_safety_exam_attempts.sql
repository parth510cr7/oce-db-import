-- Add station metadata, patient/finding structures, safety expectations, and exam attempts

-- 1) Station metadata (per case)
alter table cases
  add column if not exists reading_seconds integer,
  add column if not exists time_limit_seconds integer,
  add column if not exists setting text,
  add column if not exists role_level text,
  add column if not exists allowed_actions jsonb not null default '[]'::jsonb,
  add column if not exists probe_budget integer,
  add column if not exists exam_mode jsonb not null default '{}'::jsonb;

-- 2) Patient profile + findings + investigations (normalized but flexible via jsonb)
create table if not exists case_patient_profiles (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null unique references cases(id) on delete cascade,
  profile jsonb not null, -- demographics, PMH/PSH, meds/allergies, social, goals, communication_style
  created_at timestamptz not null default now()
);

create table if not exists case_initial_vitals (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null unique references cases(id) on delete cascade,
  vitals jsonb not null, -- {hr,bp,rr,spo2,temp,pain,...} + timestamps
  created_at timestamptz not null default now()
);

create table if not exists case_history_facts (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  key text not null,
  fact jsonb not null, -- structured fact, e.g. onset/duration/mechanism/red_flags_present
  visibility text not null default 'on_request', -- always|on_request|hidden
  unique (case_id, key)
);

create table if not exists case_exam_findings (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  key text not null,
  finding jsonb not null, -- e.g. rom/neuro/special_tests; may include normal/abnormal, side, severity
  visibility text not null default 'on_request',
  unique (case_id, key)
);

create table if not exists case_investigations (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  key text not null,
  investigation jsonb not null, -- availability + results + reference ranges + timestamps
  visibility text not null default 'on_request',
  unique (case_id, key)
);

-- 3) Safety expectations rules (deterministic safety flagging)
create table if not exists case_safety_expectations (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  action_key text not null, -- stable action taxonomy key (e.g., ask.red_flags, advise.safety_net)
  rule_type text not null, -- required|conditional_required|forbidden
  trigger_condition jsonb, -- json logic; null for unconditional
  time_window text not null default 'anytime', -- early|anytime|before_disposition|within_seconds
  time_limit_seconds integer,
  severity_if_missed text not null default 'major', -- critical|major|minor
  domain_tags jsonb not null default '[]'::jsonb,
  scoring_effect jsonb not null default '{}'::jsonb,
  feedback_template text,
  unique (case_id, action_key, rule_type)
);

-- 4) Exam attempts (multi-station / circuit)
create table if not exists exam_attempts (
  id uuid primary key default gen_random_uuid(),
  exam_id uuid not null references exams(id) on delete cascade,
  user_id uuid not null references users(id) on delete cascade,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  status text not null default 'in_progress', -- in_progress|completed|abandoned
  overall_score numeric,
  pass_fail text, -- pass|fail|borderline
  unique (exam_id, user_id, started_at)
);

create table if not exists exam_attempt_station_runs (
  id uuid primary key default gen_random_uuid(),
  exam_attempt_id uuid not null references exam_attempts(id) on delete cascade,
  station_run_id uuid not null unique references station_runs(id) on delete cascade
);

