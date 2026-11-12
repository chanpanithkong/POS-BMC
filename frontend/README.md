# ABC Mart POS and Inventory (frontend)

Next.js frontend for the POS and Inventory Management System (PIMS-SRS-001). It runs today against an in-browser mock server and is built to move to FastAPI and PostgreSQL without rewriting screens.

## Run it

```bash
npm install
```

```bash
npm run dev
```

Open http://localhost:3000. Sample data is generated once and stored in this browser. Reset it from the account menu.

## Demo sign-in

**This sign-in is simulated and is not production security.**

The password for every account is `demo-password`. The login page has one-click buttons for each role.

| Role | Username | POS or approval PIN |
|---|---|---|
| Business Owner | owner | 7391 |
| Store Manager | manager | 2580 |
| Branch Manager | branch | 3914 |
| Cashier | cashier | 1593 |
| Inventory Manager | inventory | 6152 |
| Purchasing Officer | purchasing | 8247 |
| Warehouse Staff | warehouse | 6471 |
| Accountant | accountant | 9162 |
| Auditor | auditor | 3786 |
| System Administrator | admin | 4826 |
| Salesperson | sales | 5038 |
| Read-only User | viewer | 5429 |

## POS shortcuts

| Key | Action |
|---|---|
| F2 | Quantity |
| F3 | Focus search |
| F4 | Customer |
| F6 | Line discount |
| F7 | Price check |
| F8 | Hold |
| F9 | Held sales |
| F12 | Pay |
| Del | Remove line |
| Up, Down | Select line |

A keyboard-wedge barcode scanner works without focusing a field.

## How it is organised

| Path | Purpose |
|---|---|
| `src/app` | Routes: `(auth)`, `(dashboard)`, and the full-screen `(pos)` |
| `src/components` | `ui` (shadcn), `layout`, `shared` (table, forms, dialogs), feature components |
| `src/services` | Typed API functions, one per REST resource |
| `src/lib/api` | Transport, configuration, error type, wire-format conversion |
| `src/hooks` | Data fetching and POS commands |
| `src/stores` | Zustand client state |
| `src/types` | Domain types |
| `src/mock-server` | Stand-in backend: routes, business rules, stock ledger, seed |
| `src/mock-data` | Sample catalogue |

## Moving to the real backend

Every screen calls `src/services`, and every service goes through `apiRequest` in `src/lib/api/client.ts`. Paths follow SRS section 13.

1. Copy `.env.example` to `.env.local`.
2. Set `NEXT_PUBLIC_API_MODE=live` and `NEXT_PUBLIC_API_URL`.
3. Implement the routes in FastAPI. `src/mock-server/handlers` is a working reference for each rule, status change and error code.

JSON keys and decimal strings are converted at the HTTP boundary. The mock server's checks are for demonstration only: **all authorisation and business rules must be enforced again in FastAPI.** See the integration limits in `docs/requirements-mapping.md`.

## Requirements coverage

`docs/requirements-mapping.md` maps each of the 293 functional requirements to its screens and says what is implemented, simulated, partial or deferred.

## Checks

```bash
npx tsc --noEmit
```

```bash
npm run lint
```

```bash
npm run build
```
