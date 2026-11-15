# ABC Mart POS and Inventory (frontend)

Next.js frontend for the POS and Inventory Management System (PIMS-SRS-001). It talks to the FastAPI backend in `../backend`, which owns the PostgreSQL database and every business rule. The browser never connects to the database. For a quick look without a backend, it can also run on a built-in mock server with sample data (see [Mock mode](#mock-mode-no-backend)).

## Run it

Start the API first (see `../backend/README.md`). By default the frontend expects it at `http://localhost:8000/api/v1`.

```bash
npm install
```

```bash
npm run dev
```

Open http://localhost:3000 and sign in with an account from the backend (see [Sign-in](#sign-in)).

Settings live in `.env.local`, which is git-ignored, so each PC has its own. You only need it when the API runs at another address:

```bash
cp .env.example .env.local
```

| Variable | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | API address the browser calls |
| `NEXT_PUBLIC_API_MODE` | `live` | `mock` switches to the built-in mock server (no backend) |

These values are read when the app starts and are built into `npm run build`. Restart `npm run dev`, or build again, after changing them. Create the file by copying `.env.example` or with Notepad, not with `echo ... > .env.local` in Windows PowerShell 5.1: that saves it as UTF-16, which Next.js cannot read.

## Run it in Docker

The `Dockerfile` in this folder builds a production image of the frontend. It runs Next.js's self-contained server (`output: "standalone"`) as a non-root user on port 3000, with no source code or development tools inside. You need [Docker Desktop](https://www.docker.com/products/docker-desktop/). The first build needs internet access, because the fonts are downloaded from Google during the build.

The frontend needs the API running somewhere. Pick one of the two ways below.

### Option A: the whole system with Docker Compose (recommended)

`backend/docker-compose.yml` runs four containers together: PostgreSQL, the API, the background worker, and this frontend (`web`).

1. Create `backend\.env` from `backend\.env.example`, and fill in `DB_PASSWORD` and `SECRET_KEY`.
2. From the `backend` folder, build and start everything:

   ```bash
   docker compose --env-file .env up --build -d
   ```

3. The first time only, create the company and the first admin and owner accounts:

   ```bash
   docker compose exec api python -m scripts.bootstrap
   ```

4. Open http://localhost:3000 and sign in with those accounts.

The containers use their own PostgreSQL (published on port 5433) with data kept in a Docker volume. It is separate from any PostgreSQL installed on the PC, so it starts empty, and the demo users from `scripts.seed_demo_store` do not exist there.

### Option B: only the frontend image

Use this when the API already runs elsewhere, for example `python -m app.serve` on this PC or on a server. From this `frontend` folder:

```bash
docker build -t pims-frontend --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 .
```

```bash
docker run -d --name pims-frontend -p 3000:3000 --restart unless-stopped pims-frontend
```

Open http://localhost:3000.

### The API address is built into the image

The browser code calls the API directly, and Next.js bakes `NEXT_PUBLIC_*` values into that code during `docker build`. So:

- Set `NEXT_PUBLIC_API_URL` to the address **the users' browsers** can reach, such as `http://localhost:8000/api/v1` or `http://192.168.1.50:8000/api/v1`. Never use Docker's internal name `http://api:8000`: browsers cannot resolve it.
- Setting it with `docker run -e` has no effect. To change the address, build the image again.
- Your `.env.local` is never copied into the image (see `.dockerignore`). The address comes only from the build argument.

| Build argument | Default | Meaning |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000/api/v1` | API address used by the browser |
| `NEXT_PUBLIC_API_MODE` | `live` | `mock` builds the demo with built-in sample data and no backend |

With Compose, set the address as `PUBLIC_API_URL` in `backend\.env`, then run `up --build` again.

The API only accepts requests from the frontend's own address. In `backend\.env`, `CORS_ORIGINS` must list the exact address in the browser bar, including the port, for example `http://localhost:3000`. Restart the API after changing it.

### Using it from other PCs on the network

Say the server's IP is `192.168.1.50` (find it with `ipconfig`).

1. In `backend\.env`, set:

   ```
   PUBLIC_API_URL=http://192.168.1.50:8000/api/v1
   CORS_ORIGINS=http://192.168.1.50:3000
   ```

2. Rebuild and restart, from the `backend` folder:

   ```bash
   docker compose --env-file .env up --build -d
   ```

3. Allow ports 3000 and 8000 through Windows Firewall on the server. Run these once, as administrator:

   ```powershell
   New-NetFirewallRule -DisplayName "PIMS web" -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow
   New-NetFirewallRule -DisplayName "PIMS API" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
   ```

4. On the other PCs, open http://192.168.1.50:3000.

Keep this on a trusted local network. For access over the internet, put both behind HTTPS with a reverse proxy, and set `REFRESH_COOKIE_SECURE=true` in `backend\.env`.

### Everyday commands

Run these from the `backend` folder when using Compose.

| Task | Command |
|---|---|
| Show running containers | `docker compose ps` |
| Follow the frontend and API logs | `docker compose logs -f web api` |
| Stop everything (data is kept) | `docker compose down` |
| Start again | `docker compose --env-file .env up -d` |
| Update after `git pull` | `docker compose --env-file .env up --build -d` |
| Rebuild only the frontend | `docker compose --env-file .env up --build -d web` |

For the standalone image (option B): `docker logs -f pims-frontend` shows the logs, and `docker rm -f pims-frontend` removes the container before you run a rebuilt image.

`docker compose down -v` also deletes the database volume, and with it all the data. Don't use `-v` unless that's what you want.

### Troubleshooting

| Problem | Fix |
|---|---|
| The sign-in page lists demo accounts | The image was built in mock mode. Rebuild without `NEXT_PUBLIC_API_MODE=mock`. |
| The sign-in page loads, but signing in fails with a network error | The browser cannot reach `NEXT_PUBLIC_API_URL`. Open that address followed by `/health` in the same browser. If it fails, fix the address and rebuild. |
| The browser console shows a CORS error | `CORS_ORIGINS` in `backend\.env` doesn't match the frontend's address. Fix it and restart the API (`docker compose up -d api`). |
| "Incorrect sign-in details" with the right password | The API is using a database without that user. With Compose, run the bootstrap in step 3. |
| The frontend still calls an old address | The address is fixed at build time. Rebuild with `--build`. |
| `port is already allocated` | Something else already uses port 3000 or 8000, such as `npm run dev` or `python -m app.serve`. Stop it, or publish another port, for example `-p 3001:3000`, and add that address to `CORS_ORIGINS`. |
| The build fails while fetching fonts | The build has no internet access. Check the PC's connection or proxy and build again. |

## Sign-in

Accounts, passwords and permissions all come from the backend; the frontend has no accounts of its own. Which accounts exist depends on the database the API uses:

- **Your own database** (`pims_db`): the company and the first admin and owner accounts are created with `python -m scripts.bootstrap` in `../backend`. Other users are added on the Users screen.
- **Demo databases** (`pims_demo`, or `pims_demo_store` with about 60 days of trading): one user per role, created by `scripts.seed_demo` or `scripts.seed_demo_store`. They all share one generated password, written to `../backend/.demo-credentials`. That file is git-ignored, so check it on the PC that built the database.

| Role | Demo username | POS or approval PIN |
|---|---|---|
| Business Owner | owner | |
| Store Manager | manager | 2468 |
| Branch Manager | branch | |
| Cashier (Toul Kork) | cashier | 1593 |
| Cashier (BKK, `pims_demo_store` only) | cashier2 | 2580 |
| Inventory Manager | inventory | |
| Purchasing Officer | purchasing | |
| Warehouse Staff | warehouse | |
| Accountant | accountant | |
| Auditor | auditor | |
| System Administrator | admin | |
| Salesperson | sales | |
| Read-only User | viewer | |

The cashier PIN signs in at a registered POS terminal. The manager PIN approves discounts, voids and other supervisor actions at the till. Only the System Administrator can edit roles.

If the right password is refused with "Incorrect sign-in details", the API is usually running on a database without that user, for example `pims_db` instead of a demo database. Check `DB_NAME` in `../backend/.env`, or the `$env:DB_NAME` the API was started with.

## Mock mode (no backend)

Set `NEXT_PUBLIC_API_MODE=mock` in `.env.local` and restart `npm run dev`. The screens then run on an in-browser mock server instead of the API. Sample data is generated once and stored in that browser; reset it from the account menu.

**Mock sign-in is simulated and is not production security.** The mock checks are for demonstration only; the real rules are enforced by the backend. The password for every mock account is `demo-password`, and the sign-in page shows one-click buttons for each role. These accounts and PINs exist only in mock mode:

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
| `src/lib/api` | Transport, configuration, error type, wire-format conversion, permission mapping |
| `src/hooks` | Data fetching and POS commands |
| `src/stores` | Zustand client state |
| `src/types` | Domain types |
| `src/mock-server` | Mock mode only: in-browser stand-in for the API (routes, rules, stock ledger, seed) |
| `src/mock-data` | Mock mode only: sample catalogue |

## How it talks to the backend

Every screen calls `src/services`, and every service goes through `apiRequest` in `src/lib/api/client.ts`. Paths follow SRS section 13. In mock mode the same requests go to `src/mock-server` instead, so screens never know which one they are using.

- **Wire format:** the API uses snake_case JSON and sends amounts as decimal strings. `src/lib/api/casing.ts` converts keys to camelCase and amounts to numbers on the way in, and back on the way out.
- **Sign-in:** the access token is kept in memory only. The session survives page reloads through an HttpOnly refresh cookie that the browser sends to `/auth/refresh`. Refreshes are single-flight, because the backend treats a reused refresh token as theft and ends the session.
- **Permissions:** the backend names permissions `module.resource.action`; screens use shorter keys. `src/lib/api/permissions.ts` translates between them using `permission-map.ts`. That file is generated by `python -m scripts.frontend_permissions` in `../backend`, so regenerate it when backend permissions change.
- **POS terminal:** the chosen terminal is saved in the browser and sent as the `X-Terminal-Id` header. Saved IDs left over from mock mode are discarded. After switching to another database, pick the terminal again on the POS screen.
- **Security:** hiding a button or screen here is only for usability. The backend checks every permission, limit, price and total again, and never trusts amounts sent by the browser.

See the integration notes in `docs/requirements-mapping.md`.

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
