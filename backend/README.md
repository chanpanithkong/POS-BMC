# PIMS API — POS and Inventory Management System backend

FastAPI + PostgreSQL backend for the Next.js frontend in `../frontend`, built from PIMS-SRS-001 v1.0.
The frontend talks only to this API; it never connects to PostgreSQL.

| | |
|---|---|
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/api/v1/openapi.json |
| API base | http://localhost:8000/api/v1 |

Design documents are in [`docs/`](docs): implementation plan, database design, generated ERD, endpoint catalogue and requirements traceability.

## Requirements

- Python 3.12 or newer (this project uses a uv-managed 3.12 in `.venv`)
- PostgreSQL 16 or newer, running on `localhost:5432`

## First-time setup (Windows PowerShell)

Run everything from the `backend` folder.

```powershell
cd C:\Users\James\Documents\next\pos\backend
```

1. Create the virtual environment and install dependencies (skip if `.venv` already exists):

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt
```

2. Create `.env` from the example, then fill in `DB_PASSWORD` and `SECRET_KEY`. Never commit `.env`.

```powershell
Copy-Item .env.example .env
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
notepad .env
```

3. Create the databases. This creates `pims_db` and `pims_test_db` only if they are missing, and never drops or changes an existing database.

```powershell
.venv\Scripts\python.exe -m scripts.create_databases
```

4. Apply migrations to `pims_db`:

```powershell
.venv\Scripts\alembic.exe upgrade head
```

5. Create the company and the first administrator and owner accounts. It refuses to run once any user exists. Enter passwords at the prompt, or leave them blank to have strong ones generated and shown once.

```powershell
.venv\Scripts\python.exe -m scripts.bootstrap
```

## Run the API

```powershell
.venv\Scripts\python.exe -m app.serve --reload
```

Use `app.serve` on Windows rather than plain `uvicorn`: psycopg's async driver needs the selector event loop, which the launcher sets. In Linux or Docker, `uvicorn app.main:app` works as well.

## Try the frontend against the API (demo database)

`scripts.seed_demo` creates a separate `pims_demo` database with clearly labelled sample data: 2 branches, 3 terminals, 5 products, 12 users, one per role. It refuses to touch `DB_NAME` or any database without "demo" in its name. The shared demo password is generated and written to `backend/.demo-credentials`, which is git-ignored. Set `DEMO_PASSWORD` to choose it yourself.

```powershell
.venv\Scripts\python.exe -m scripts.seed_demo
$env:DB_NAME="pims_demo"; .venv\Scripts\python.exe -m app.serve
```

For a shop that looks lived-in, `scripts.seed_demo_store` builds `pims_demo_store` instead. It contains 42 products, 28 customers, 5 suppliers and about 60 days of trading at two branches: sales, voids, returns, weekly purchase orders with deliveries and supplier invoices, transfers, damage write-offs, expenses, promotions, and closed cash sessions. Every record goes through the real API, with a simulated clock stepping through the days, so stock, costing, approvals and numbering behave exactly as in production. Today's tills are left open, with a held sale, a PO awaiting approval and a transfer in transit. It takes about 10 minutes and uses the same demo password.

```powershell
.venv\Scripts\python.exe -m scripts.seed_demo_store
$env:DB_NAME="pims_demo_store"; .venv\Scripts\python.exe -m app.serve
```

In `frontend/.env.local` set `NEXT_PUBLIC_API_MODE=live` and `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`, then run `npm run dev`. Low-stock alerts appear after a worker pass (`$env:DB_NAME="pims_demo"; .venv\Scripts\python.exe -m app.workers.run --once`).

## Background worker

Releases expired stock reservations, re-checks stock alerts, sends password-reset emails (when SMTP is set in `.env`), reminds managers about sessions left open, and clears old idempotency keys. Run it next to the API:

```powershell
.venv\Scripts\python.exe -m app.workers.run
```

Use `--once` to run a single pass, for example from Windows Task Scheduler.

## Tests

Tests use only `TEST_DB_NAME` (default `pims_test_db`). The suite refuses to start if that name equals `DB_NAME` or does not contain `test`. Each run rebuilds the test schema from the migrations (downgrade, then upgrade). Your development database is never touched.

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m pytest tests\unit
.venv\Scripts\ruff.exe check .
```

If `DB_PASSWORD` is empty or the test database is unreachable, the database tests are skipped with the reason shown, and the unit tests still run.

## Other commands

```powershell
# New migration after changing models (review the generated file before applying)
.venv\Scripts\alembic.exe revision --autogenerate -m "describe the change"
# Check that models and migrations agree
.venv\Scripts\alembic.exe check
# Regenerate docs/ERD.md from the models
.venv\Scripts\python.exe -m scripts.erd
# Run one worker pass
.venv\Scripts\python.exe -m app.workers.run --once
# Re-seed reference data (permissions, currencies, location types); safe to repeat
.venv\Scripts\python.exe -m scripts.seed
```

## Docker

```powershell
docker compose --env-file .env up --build
```

Compose starts PostgreSQL 16, published on port **5433** so it does not clash with a local server on 5432, the API on port 8000, and the background worker. Uploaded files are kept in the `pims_storage` volume. Migrations run when the API starts. If `DB_PASSWORD` contains `@`, `:`, `/` or `%`, URL-encode it in the compose `DATABASE_URL`.

## Authentication for the frontend

- `POST /api/v1/auth/login` returns `{access_token, token_type, expires_in, user}`, where `user` includes `permissions`, `limits`, `branch_ids` and `home_path`. Send the access token as `Authorization: Bearer <token>`. It lasts 15 minutes.
- The refresh token is an HttpOnly cookie (`pims_refresh`, path `/api/v1/auth`). Call `POST /api/v1/auth/refresh` with `credentials: "include"` to rotate it. Reusing an old refresh token ends the session.
- Sessions end after 30 minutes idle or 12 hours in total.
- Five failed sign-ins in 15 minutes lock the account for 15 minutes.
- Errors always use `{"error": {"code", "message", "details", "correlation_id"}}`. Records outside the caller's company or branch scope return 404.

## Project layout

```
app/
  api/v1/endpoints/   HTTP routes only: validation, permission dependency, call a service
  services/           Business rules and transaction boundaries (one commit per command)
  repositories/       Reusable queries
  models/             SQLAlchemy 2.0 models
  schemas/            Pydantic v2 request/response models (unknown fields rejected)
  core/               Settings, security, permissions catalogue, errors, logging
  middleware/         Correlation ID
  db/                 Engine, session, declarative base
alembic/versions/     Migrations
scripts/              create_databases, bootstrap, seed, erd
tests/unit|api|integration
```
