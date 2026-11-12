# Installing PIMS on another Windows PC

This sets up the backend (FastAPI + PostgreSQL) and the frontend (Next.js) from scratch. Commands are for **PowerShell**. Allow about 30 minutes.

The frontend talks only to the API, and the API is the only thing that connects to PostgreSQL.

## 1. Install the tools

| Tool | Version | Where |
|---|---|---|
| Git | any recent | https://git-scm.com/download/win |
| Python | **3.12** | https://www.python.org/downloads/ (tick "Add python.exe to PATH") |
| Node.js | **22 LTS or newer** (Next.js 16 needs 20.9+) | https://nodejs.org |
| PostgreSQL | **16 or newer** | https://www.postgresql.org/download/windows/ |

During the PostgreSQL install, choose a password for the `postgres` user and keep port **5432**. You only need the server; Stack Builder can be skipped.

Check them in a new PowerShell window:

```powershell
git --version
py -3.12 --version
node -v
npm -v
```

## 2. Get the code

```powershell
cd $HOME\Documents
git clone https://github.com/chanpanithkong/POS-BMC.git pos
cd pos
git checkout backend-phases-7-8-live-frontend
```

Use whichever branch holds the latest work (`main` once it has been merged). Files that are git-ignored never travel with the clone: `backend/.env`, `backend/.demo-credentials`, `frontend/.env.local`, `node_modules` and `.venv`. You create these below.

## 3. Backend

```powershell
cd $HOME\Documents\pos\backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

(If you use `uv`: `uv venv --python 3.12 .venv` then `uv pip install --python .venv\Scripts\python.exe -r requirements-dev.txt`.)

### Configuration

```powershell
Copy-Item .env.example .env
.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
notepad .env
```

In `.env`, set:

- `DB_PASSWORD` to the PostgreSQL password from step 1.
- `SECRET_KEY` to the long random string the command above printed. Generate a new one on each PC; never copy it from another machine or commit it.

Leave the rest as they are for a single-PC setup.

### Database

```powershell
.venv\Scripts\python.exe -m scripts.create_databases   # creates pims_db and pims_test_db if missing; never drops anything
.venv\Scripts\alembic.exe upgrade head                  # builds the tables in pims_db
```

Then pick one:

- **Real use:** create the company and the first admin and owner accounts. Enter passwords at the prompts, or leave them blank and strong ones are generated and shown once.

  ```powershell
  .venv\Scripts\python.exe -m scripts.bootstrap
  ```

- **Try it with sample data:** build the demo shop, about 60 days of trading, in a separate `pims_demo_store` database. It takes about 10 minutes. The demo password is written to `backend\.demo-credentials`.

  ```powershell
  .venv\Scripts\python.exe -m scripts.seed_demo_store
  ```

### Start the API

```powershell
.venv\Scripts\python.exe -m app.serve
```

For the demo database: `$env:DB_NAME="pims_demo_store"; .venv\Scripts\python.exe -m app.serve`

Open http://localhost:8000/docs. If the API page loads, the backend works. Leave this window open.

On Windows, always start the API with `app.serve`, not plain `uvicorn`: the database driver needs the event loop that `app.serve` sets up.

Optional, in a second window: the background worker, which releases expired stock holds, raises stock alerts, sends emails and reminds about open tills.

```powershell
cd $HOME\Documents\pos\backend
.venv\Scripts\python.exe -m app.workers.run
```

For the demo database, set `$env:DB_NAME="pims_demo_store"` first.

## 4. Frontend

In a new PowerShell window:

```powershell
cd $HOME\Documents\pos\frontend
npm ci
Copy-Item .env.example .env.local
```

The copied `.env.local` already uses the real API:

```
NEXT_PUBLIC_API_MODE=live
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

Change it only if the API runs on another address (see section 5). Edit it with `notepad .env.local`. Don't create it with `echo ... > .env.local` in Windows PowerShell 5.1: that saves the file as UTF-16, which Next.js cannot read.

The real API is the default even without the file. `NEXT_PUBLIC_API_MODE=mock` switches to the built-in sample data with no backend, for a quick look only. On the sign-in page, mock mode shows a list of demo accounts; the real API does not.

Run it:

```powershell
npm run dev
```

Open http://localhost:3000 and sign in.

For everyday use, a production build is faster:

```powershell
npm run build
npm run start
```

`NEXT_PUBLIC_*` values are fixed into the build, so run `npm run build` again after changing `.env.local`.

## 5. Using it from other PCs on the same network (optional)

Run everything on one "server" PC, and open the browser on the other PCs. Say the server's IP is `192.168.1.50`; find it with `ipconfig`.

1. In `backend\.env` on the server, set:

   ```
   CORS_ORIGINS=http://192.168.1.50:3000
   FRONTEND_URL=http://192.168.1.50:3000
   ```

2. Start the API so it listens on the network:

   ```powershell
   .venv\Scripts\python.exe -m app.serve --host 0.0.0.0
   ```

3. In `frontend\.env.local`, set the URL the *browsers* will use, then rebuild:

   ```
   NEXT_PUBLIC_API_URL=http://192.168.1.50:8000/api/v1
   ```

   ```powershell
   npm run build
   npm run start -- -H 0.0.0.0
   ```

4. Allow the two ports through Windows Firewall. Run this once, as administrator:

   ```powershell
   New-NetFirewallRule -DisplayName "PIMS web" -Direction Inbound -Protocol TCP -LocalPort 3000 -Action Allow
   New-NetFirewallRule -DisplayName "PIMS API" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
   ```

5. On the other PCs, open http://192.168.1.50:3000.

Keep this on a trusted local network. For access over the internet, put both behind HTTPS (for example a reverse proxy) and set `REFRESH_COOKIE_SECURE=true`.

## 6. Check everything (optional)

```powershell
cd $HOME\Documents\pos\backend
.venv\Scripts\python.exe -m pytest      # uses only pims_test_db; your data is never touched
cd ..\frontend
npx tsc --noEmit -p .
npm run lint
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `password authentication failed` | `DB_PASSWORD` in `backend\.env` does not match the PostgreSQL password. |
| `connection refused` on port 5432 | PostgreSQL is not running. Start the "postgresql-x64-NN" service in Services. |
| Sign-in says the username or password is wrong | The API is pointing at a database without that user. `pims_db` has only the accounts you made with `scripts.bootstrap`; demo users exist only in `pims_demo_store`. Check which `DB_NAME` the API window was started with. |
| "This could not be loaded" or "Invalid request" after switching databases | Old branch or terminal choices are saved in the browser. Pick the terminal again on the POS screen, or clear the site data for localhost:3000. |
| Port 8000 or 3000 already in use | Another copy is running. Close it, or use `--port 8001` and change `NEXT_PUBLIC_API_URL` to match. |
| Browser shows a CORS error | `CORS_ORIGINS` in `backend\.env` must exactly match the address in the browser bar, including the port. Restart the API after changing it. |
| Frontend still calls the old API address | `NEXT_PUBLIC_API_URL` is fixed at build time. Run `npm run build` again. |
| Frontend shows demo accounts on the sign-in page and doesn't use the API | It is in mock mode. Check that `frontend\.env.local` doesn't say `NEXT_PUBLIC_API_MODE=mock`, then stop and restart `npm run dev`, or run `npm run build` again for `npm run start`. |
