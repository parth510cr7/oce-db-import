## Ontario OCE OSCE Simulator (DB + Importer)

This repo contains:
- A **PostgreSQL schema** (SQL migrations) for users, cases, rubric domains/criteria, responses, scores, and feedback history
- A **document ingestion pipeline** that converts PDFs (including an exported `Domains PPT` PDF) into normalized DB records with provenance

### Prerequisites
- Python 3.9+
- A Postgres database (local install or Docker)

### Environment
Set a `DATABASE_URL` in the standard libpq format:

```bash
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/oce_sim"
```

### Apply DB migrations

```bash
python3 -m pip install -r requirements.txt
# Prefer running modules so imports resolve consistently:
python3 -m db.apply_migrations
```

### Import documents

```bash
python3 -m importer.import_sources \
  --source "/path/to/Domains PPT.pdf" \
  --kind pdf
```

### Export everything to JSON files

This exports:
- full extracted text (`source_chunks`) per document
- ingestions + extractions (including warnings)
- rubrics (sets/domains/criteria)
- cases/prompts/expected elements

```bash
python3 -m exporter.export_to_json --out exports
```

### Optional: install as a CLI

If you want an `oce` command (instead of `python -m ...`), create a virtualenv and install editable:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U pip
python3 -m pip install -e .
oce --help
```

