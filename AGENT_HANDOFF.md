## Agent handoff (keep up to date)

### Repo purpose
AI-powered OSCE-style physiotherapy interview simulator with:
- Postgres schema + migrations
- Importer (PDF → sources/chunks/extractions + cases/rubrics)
- Case generator (Dutton-based paired Case1/Case2)
- Examiner marksheet JSON validator + DB writeback
- Deterministic pass/fail computation stored on `station_runs`
- Runtime fact gating (always/on_request/hidden + prereq_actions) + station event logging

### Local environment
- **Database**: `DATABASE_URL="postgresql://parth@localhost:5432/oce_sim"`
- **CLI**: install once:
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -e .`
  - Then run `oce ...`

### Key commands (via `oce`)
- **Migrate DB**: `oce migrate`
- **Generate cases**: `oce generate-dutton-cases --status draft`
- **Export JSON (safe default)**: `oce export-json --out exports` (raw text excluded unless `--unsafe-include-raw-text`)
- **Apply marksheet JSON**: `oce apply-marksheet --marksheet <file>`
- **Station runtime helpers (for testers)**:
  - `oce station start --attempt-id <uuid> [--exam-station-id <uuid>]`
  - `oce station prompt-delivered --station-run-id <uuid> --prompt-id <uuid> --order-index 1 --prompt-type probe`
  - `oce station response --station-run-id <uuid> --attempt-id <uuid> --prompt-id <uuid> --text "..."` (upserts `responses`)
  - `oce station action --station-run-id <uuid> --action-key ask.red_flags`
  - `oce station probe-request --station-run-id <uuid> [--kind clarification]` (enforces `probe_budget` and logs request/decision)
  - `oce station navigate --station-run-id <uuid> --to-order-index <n>` (enforces `no_backtracking` when enabled)
  - `oce enforce-station --station-run-id <uuid>` (emits policy snapshot + time warnings + locks at expiry)
- **Maintenance**
  - `oce backfill-allowed-actions` (converts legacy free-text `cases.allowed_actions` to canonical action keys where possible)

### Current schema highlights
- **Core**: `users`, `cases`, `case_prompts`, `attempts`, `responses`
- **Rubric**: `rubric_sets`, `rubric_domains`, `rubric_criteria`
- **Scoring**:
  - `scores` now includes `rationale`, `evidence_spans`, `scored_by`, `scored_at` (migration `007`)
  - `global_rating_marks`, `checklist_marks`, `critical_flags`
- **Runtime**:
  - `station_runs` has `state`, `current_prompt_order_index`, plus persisted results (`pass_fail`, `percentage`, `result_json`) (migration `006`)
  - `station_events` is append-only audit log
- **Fact gating**: `case_history_facts`, `case_exam_findings`, `case_investigations` with `visibility` + JSON payloads (may include `prereq_actions`)

### Event taxonomy
- New normalized dot-types are emitted (and legacy types are also emitted for backwards compat):
  - `action.performed`, `action.denied`
  - `fact.revealed`, `fact.withheld`
  - `prompt.delivered`, `response.received`
  - `time.warning`
  - `station.lifecycle.locked`, `station.lifecycle.ended`
  - `scoring.result_computed`
  - `policy.snapshot`

### Recent work (today)
- Packaging/CLI verified end-to-end (`pip install -e .`, `oce migrate`, `oce apply-marksheet`, `oce export-json`)
- Added safer exports (raw text excluded by default)
- Tightened EvidenceSpan validation and persisted domain rationales/evidence
- Added runtime enforcer (`runtime/enforce_station.py`) + station CLI helper (`runtime/station_cli.py`) and wired them into `oce`

### Next tasks (agreed direction)
- Make action taxonomy canonical (stop free-text allowed_actions mismatch; add strict vs practice modes). ✅ Implemented canonical keys + deny unknown; strict mode supported via `strict_actions`.
- Enforce station metadata fully:
  - `reading_seconds`, `time_limit_seconds/active_seconds`, `probe_budget`, `no_backtracking`
  - emit deterministic time/prompt/lock events
- Add deterministic anti-gaming caps based on expected elements + anchored evidence.
- Add PHI/retention controls (don’t persist verbatim quotes by default; TTL purge scripts).

