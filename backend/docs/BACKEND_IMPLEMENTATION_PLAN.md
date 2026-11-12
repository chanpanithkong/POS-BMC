# Backend implementation plan

Source of truth: PIMS-SRS-001 v1.0 (Draft for Review, 27 October 2026). Where the SRS marks something as an assumption (A-nn), a decision needing approval (D-nn) or a confirmation item (V-nn), this backend keeps it configurable and labels it as such. It is never presented as a confirmed rule.

## 1. Architecture

A modular monolith (SRS 12.1), one FastAPI process plus a worker process later.

```
Next.js (browser) ──HTTPS──> FastAPI /api/v1 ──> services ──> repositories ──> PostgreSQL
                                   │                 │
                                   │                 └── outbox_events ──> worker (alerts, print jobs, emails)
                                   └── middleware: correlation ID, error envelope, CORS
```

| Layer | Responsibility | Never does |
|---|---|---|
| `api/v1/endpoints` | HTTP: parse, call one service, return schema | Business rules, SQL |
| `schemas` | Pydantic v2 request and response models, wire format | Database access |
| `services` | Business rules, transactions, locking, audit, outbox | HTTP concerns |
| `repositories` | Queries and persistence for one aggregate | Commit transactions |
| `models` | SQLAlchemy 2.0 tables | Logic |
| `core` | Config, security, permissions, errors, logging | |

A unit of work wraps every command: one request, one database transaction (SRS 13.1). The endpoint dependency opens it, the service does the work, and it commits once at the end or rolls back on any error.

## 2. Technology

| Need | Choice | Note |
|---|---|---|
| Runtime | Python 3.12 (private install via uv) | |
| Web | FastAPI, Uvicorn | |
| ORM | SQLAlchemy 2.0 async with psycopg 3 | `postgresql+psycopg://` works for sync (Alembic) and async (app) |
| Migrations | Alembic | No `create_all` outside tests |
| Validation | Pydantic v2, pydantic-settings | Unknown fields rejected on commands (NFR-SEC-005) |
| Passwords and PINs | argon2-cffi, Argon2id (FR-AUTH-004) | |
| Tokens | PyJWT access token (15 min); opaque rotating refresh token in an HttpOnly cookie, stored hashed (FR-AUTH-001) | |
| Tests | pytest, pytest-asyncio, HTTPX against `pims_test_db` | Never against `pims_db` |
| Excel | openpyxl | Reports and imports |
| PDF | Deferred: WeasyPrint needs GTK on Windows | See section 6 |

## 3. Cross-cutting rules

| Concern | Implementation | SRS |
|---|---|---|
| Wire format | snake_case JSON; money and quantities as decimal strings; the frontend converts at its HTTP boundary | 13.1 |
| Errors | `{"error": {"code", "message", "details", "correlation_id"}}` for every error, including 422 and 500 | 13.1 |
| Correlation IDs | `X-Correlation-Id` accepted or generated, returned on every response, written to logs | NFR-MNT-005 |
| Lists | `{"items", "total", "next_cursor"}` with `limit` (max 200), `offset` or `cursor`, `sort=-field` | 13.1 |
| Idempotency | `Idempotency-Key` header stored in `idempotency_keys` (scope, key, request hash, status, response). Same key and body returns the stored response; a different body returns 409 `IDEMPOTENCY_KEY_REUSED`; in progress returns 409 `REQUEST_IN_PROGRESS` | 13.1, BR-PAY-002 |
| Optimistic concurrency | `version` on drafts; `If-Match` header; mismatch returns 409 `VERSION_CONFLICT` | 13.1 |
| Pessimistic locking | `SELECT … FOR UPDATE` on sale, balance rows (sorted order), sequence rows, document headers | 11.9 |
| Authorisation | Permission check plus scope filter in a dependency on every route; out-of-scope IDs return 404 | FR-AUTH-009, BR-SEC-001 |
| Cost visibility | Cost fields removed from responses without `inventory.cost.view` | BR-SEC-003 |
| Audit | Append-only `audit_logs` with a SHA-256 hash chain; a trigger blocks UPDATE and DELETE | BR-AUD-001, NFR-SEC-011 |
| Outbox | `outbox_events` written in the same transaction; the worker publishes after commit | 12.6 |
| Time | UTC `timestamptz`; `business_date` derived from the branch's day cut-off | BR-SAL-008 |

## 4. Phases

Each phase ends with migrations, tests run against `pims_test_db`, an update to `REQUIREMENTS_TRACEABILITY.md`, and a report. Phases that introduce business-rule decisions stop for approval.

| Phase | Scope | SRS modules | Key tests |
|---|---|---|---|
| 1 Foundation | Project layout, config, async DB session, Alembic, error envelope, correlation IDs, CORS, health check, Swagger and ReDoc, organisation and identity schema, seed of roles, permissions, currencies, location types; secure admin bootstrap | ORG (schema) | Health, error format, migration up and down |
| 2 Authentication | Login, logout, refresh rotation with reuse detection, PIN login, lockout, sessions, users, roles, employees, scopes, approvals (supervisor PIN), audit log | AUTH | Unauthorised access, lockout, SoD, scope 404 |
| 3 Organisation and catalogue | Companies, branches, warehouses, locations, terminals, tax codes, rates, numbering; categories, brands, units, conversions, products, variants, barcodes, prices and resolution, price history | ORG, PRD, CAT, PRC | SKU and barcode uniqueness, conversions, price resolution order |
| 4 Inventory | Movement service, balances, reservations, reconciliation, adjustments, transfers, counts, WAC costing, alerts | INV, CST, ADJ, TRF, ALR | Ledger equals balances, rollback, transfer conservation, delta counts |
| 5 POS and payments | Cashier sessions, draft sales, pricing engine, payments, finalization, void, receipts and numbering, returns, refunds, exchanges | POS, PAY, CSH, SAL, DOC, RET | Duplicate finalize, duplicate payment, concurrent last unit, refund limits, session variance |
| 6 Purchasing and customers | Suppliers, POs and approval, goods receiving, supplier invoices, purchase returns, customers and groups | PUR, GRN, CUS | Single posting, tolerance approval, creator cannot approve |
| 7 Reports and dashboard | 34 reports with reconciliation checks, role dashboards, CSV and Excel exports | RPT, DSH, BRN | Report totals equal dashboard, cost hiding |
| 8 Advanced | Notifications, imports, expenses, promotions and loyalty (optional) | NTF, IMP, EXP, PRM | Import atomic commit and rollback |

### Module dependencies

```
AUTH ─┬─> ORG ─> CAT ─> PRD ─> PRC ─────────────┐
      │                      └─> INV/CST ─┬─> POS/PAY/CSH/SAL/DOC ─> RET
      │                                   ├─> PUR/GRN
      │                                   ├─> TRF, ADJ, ALR
      └── audit, idempotency, outbox ─────┴─> RPT/DSH ─> NTF, IMP
```

## 5. Critical transaction boundaries

| Command | Locks, in order | Effects in one transaction |
|---|---|---|
| Finalize sale | idempotency key, sale row, balance rows sorted by (location, product, variant, batch), receipt sequence row | Re-price, verify payments, check stock, SALE movements, balances, cost snapshots, receipt number, audit, outbox |
| Record payment | idempotency key, sale row | Payment row (unique provider reference), sale totals |
| Void sale | sale row, session row, balances | SALE_VOID movements, payment reversal, audit |
| Return or exchange | sale row, sale lines, balances, session | Return document, movements by disposition, refunds, optional new sale |
| Post goods receipt | receipt row, PO row, balances | Movements, WAC update, PO received quantities |
| Dispatch or receive transfer | transfer row, balances | Movements to or from IN_TRANSIT |
| Post adjustment or count | document row, balances | ADJUSTMENT or COUNT_VARIANCE movements as deltas |
| Close cashier session | session row | Expected cash, variance, approval state |
| Import commit | import batch row | All rows or none |

## 6. Decisions and open items

| Item | Status in SRS | Backend approach |
|---|---|---|
| D-01 Offline POS | Open | Online only; idempotent APIs make offline sync possible later |
| D-04 Payment providers | Open | Cash; card, QR and transfer by verified reference; provider adapter interface left for later |
| D-05 Costing method | Open | Weighted average, company scope, behind a costing service |
| D-06 Negative stock | Open | Blocked by default; per-category flag |
| D-07 Reservations | Open | Short reservation only during electronic payment |
| D-11 Credit sales | Open | Not enabled |
| D-12 Role matrix | Open | SRS 4.3 proposed defaults seeded; editable |
| D-13 SoD strictness | Open | Strict, with a reduced-SoD company setting that flags exceptions |
| V-01 Tax | Needs confirmation | Tax codes are configuration; no Cambodian rate is seeded as fact |
| V-02 Receipt content | Needs confirmation | Template fields configurable |
| V-03 Providers | Needs confirmation | Reference-based methods only |
| PDF generation | Implementation choice | WeasyPrint needs native GTK on Windows. Receipts and invoices are returned as structured JSON first; the PDF renderer will be chosen with you in Phase 5 |
| Permission keys | SRS 4.2 | Backend uses `module.resource.action`. The Next.js frontend currently uses shorter keys, so a key map is provided and the frontend constants need updating |
| Hold and resume | SRS 13.2 uses PATCH; brief lists `POST /sales/{id}/hold` | Both: explicit action endpoints (SRS 13.4) plus the PATCH operations the frontend already sends |

## 7. Frontend integration

The frontend in `../frontend` already calls these paths through `src/lib/api/client.ts`. Switching from the mock server needs:

1. `NEXT_PUBLIC_API_MODE=live` and `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`.
2. The permission-key map from section 6.
3. Login response handling: the backend sets the refresh cookie and returns `access_token`.

Endpoints and response shapes follow `src/types` in the frontend wherever the SRS allows, so screens do not need rewriting.
