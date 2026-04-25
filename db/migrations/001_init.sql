-- Core schema for OCE OSCE simulator

create extension if not exists pgcrypto;

-- Users
create table if not exists users (
  id uuid primary key default gen_random_uuid(),
  email text unique not null,
  name text,
  role text not null default 'student',
  created_at timestamptz not null default now()
);

-- Content provenance + ingestion
create table if not exists sources (
  id uuid primary key default gen_random_uuid(),
  kind text not null, -- pdf/pptx/web
  filename text not null,
  checksum text not null,
  uploaded_at timestamptz not null default now()
);

create table if not exists source_chunks (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references sources(id) on delete cascade,
  chunk_index integer not null,
  text text not null,
  page_from integer,
  page_to integer,
  metadata jsonb not null default '{}'::jsonb,
  unique (source_id, chunk_index)
);

create table if not exists ingestions (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references sources(id) on delete cascade,
  status text not null, -- queued/running/succeeded/failed
  started_at timestamptz,
  finished_at timestamptz,
  error_text text
);

create table if not exists extractions (
  id uuid primary key default gen_random_uuid(),
  ingestion_id uuid not null references ingestions(id) on delete cascade,
  extractor_version text not null,
  output_json jsonb not null,
  warnings jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

-- Rubric model (versioned)
create table if not exists rubric_sets (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  version text not null,
  case_type text not null, -- assessment/treatment_management/both
  active boolean not null default false,
  created_at timestamptz not null default now(),
  unique (name, version)
);

create table if not exists rubric_domains (
  id uuid primary key default gen_random_uuid(),
  rubric_set_id uuid not null references rubric_sets(id) on delete cascade,
  key text not null, -- physio_expertise, communication, ...
  display_name text not null,
  default_weight numeric,
  unique (rubric_set_id, key)
);

create table if not exists rubric_criteria (
  id uuid primary key default gen_random_uuid(),
  rubric_domain_id uuid not null references rubric_domains(id) on delete cascade,
  key text not null,
  description text not null,
  anchors jsonb not null, -- score anchors/labels per rubric source
  unique (rubric_domain_id, key)
);

-- Case content
create table if not exists cases (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  case_type text not null, -- case1_assessment/case2_treatment_management
  setting text,
  msk_focus boolean,
  difficulty text,
  source_id uuid references sources(id) on delete set null,
  status text not null default 'draft', -- draft/published
  created_at timestamptz not null default now()
);

create table if not exists case_prompts (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  order_index integer not null,
  prompt_text text not null,
  prompt_audio_url text,
  prompt_type text not null, -- stem/probe/instruction
  unique (case_id, order_index)
);

create table if not exists case_expected_elements (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  rubric_criterion_id uuid references rubric_criteria(id) on delete set null,
  expected_text text not null,
  importance text not null default 'should' -- must/should/nice
);

create table if not exists case_rubric_overrides (
  id uuid primary key default gen_random_uuid(),
  case_id uuid not null references cases(id) on delete cascade,
  rubric_domain_id uuid not null references rubric_domains(id) on delete cascade,
  weight_override numeric,
  unique (case_id, rubric_domain_id)
);

-- Attempts / responses / scoring / feedback
create table if not exists attempts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references users(id) on delete cascade,
  case_id uuid not null references cases(id) on delete cascade,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  modality text not null, -- voice/text
  transcription jsonb not null default '{}'::jsonb
);

create table if not exists responses (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references attempts(id) on delete cascade,
  prompt_id uuid not null references case_prompts(id) on delete cascade,
  response_text text,
  response_audio_url text,
  responded_at timestamptz not null default now(),
  unique (attempt_id, prompt_id)
);

create table if not exists scores (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references attempts(id) on delete cascade,
  rubric_domain_id uuid not null references rubric_domains(id) on delete cascade,
  score_value numeric not null,
  max_value numeric not null,
  weight_applied numeric,
  unique (attempt_id, rubric_domain_id)
);

create table if not exists feedback_items (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null references attempts(id) on delete cascade,
  rubric_domain_id uuid references rubric_domains(id) on delete set null,
  criterion_id uuid references rubric_criteria(id) on delete set null,
  strength_text text,
  gap_text text,
  suggestion_text text,
  evidence_spans jsonb not null default '[]'::jsonb
);

create table if not exists feedback_summaries (
  id uuid primary key default gen_random_uuid(),
  attempt_id uuid not null unique references attempts(id) on delete cascade,
  overall_summary text,
  next_steps text,
  generated_by text,
  created_at timestamptz not null default now()
);

