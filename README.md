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
python3 db/apply_migrations.py
```

### Import documents

```bash
python3 -m importer.import_sources \
  --source "/path/to/Domains PPT.pdf" \
  --kind pdf
```

