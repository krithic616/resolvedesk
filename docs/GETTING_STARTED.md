# VS Code walkthrough — local setup

## 1. Get the code

Install Python 3.12 and Git. In a terminal:

```bash
git clone https://github.com/krithic616/resolvedesk.git
cd resolvedesk
code .
```

The repository is private. Authenticate Git with your GitHub account when prompted. If `code` is unavailable, open the folder through VS Code's File menu.

## 2. Create a virtual environment

VS Code → Terminal → New Terminal. On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, use `.venv\Scripts\python.exe` instead of `python` in the commands below. No system execution-policy change is needed.

On macOS/Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

Choose `.venv` with VS Code's **Python: Select Interpreter** command.

## 3. Install and configure

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
python scripts/bootstrap.py
python -m alembic upgrade head
```

The bootstrap script creates `.env` with three random role keys. Open `.env` in VS Code and copy `AGENT_API_KEY` for the interface. Never share or commit this file. No external API key or paid service is needed.

SQLite provides the easiest local start. PostgreSQL is the deployment database and is checked separately in CI. Both use the same SQLAlchemy models and Alembic migrations.

## 4. Start the API

```bash
python -m uvicorn app.main:app --reload
```

Keep this terminal open. Visit http://127.0.0.1:8000/docs for interactive API documentation. Use **Authorize** and paste one local API key to try protected endpoints.

## 5. Start the interface

Open another VS Code terminal, activate the same environment, then run:

```bash
python -m streamlit run ui/app.py
```

Open http://127.0.0.1:8501. Enter your agent API key in the sidebar.

## 6. Try one banking case

In **Create case**, enter:

- Message ID: `demo-email-001`
- Customer reference: `SYN-001`
- Subject: `Please explain this charge`
- Email: `Please explain the fee on my synthetic account and review whether a waiver is possible.`
- Category: `charges`
- Questions, one per line: `Why was this fee charged?` and `Can the charge be waived?`

Create the case and refresh the queue. Open it and inspect the two questions and `case.created` audit event. Submit the same message ID again: the API returns 409 and keeps one case. Switch to the auditor key: you can read the case, but creating a case returns 403.

After verifying intake, follow [the milestone-2 walkthrough](MILESTONE_2.md) to assign, answer, and resolve the synthetic case. No live waiver or email delivery is performed.

## 7. Verify your setup

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m alembic check
```

The three PostgreSQL concurrency tests are skipped in SQLite mode. Once this repository is published, check GitHub Actions for its PostgreSQL run. You can also run `docker compose --profile test run --build --rm verify` against local Docker.

## Optional: PostgreSQL with Docker Compose

Install Docker Desktop (or Docker Engine with Compose). Add a random alphanumeric `POSTGRES_PASSWORD` to `.env`; use at least 32 characters. This avoids special characters needing URL encoding in the connection string.

```bash
docker compose up --build
```

The database becomes healthy, the migration container applies the schema, then the API starts. The UI connects to the API over the Compose network. The database is not published on a host port. API/UI host ports bind to localhost only.

To stop:

```bash
docker compose down
```

This preserves the database volume. Back up before deleting volumes or changing schema. The local Compose setup is not a public production deployment.

## What each folder does

| Path | Purpose |
| --- | --- |
| `app/config.py` | Environment and credential validation |
| `app/auth.py` | API-enforced demo role permissions |
| `app/models.py` | Database tables and relationships |
| `app/schemas.py` | Validated request and response shapes |
| `app/main.py` | HTTP endpoints and transactional intake |
| `migrations/` | Versioned schema changes |
| `ui/app.py` | Streamlit API client |
| `tests/` | Authorization, validation, integrity, and integration checks |

## Troubleshooting

- `401`: supply a complete API key from your `.env` file.
- `403`: the auditor role is read-only.
- `409`: that message ID has already been recorded; use a new ID for a new email.
- `422`: check field constraints; references must start with `SYN-`.
- `503`: confirm the database is running and migrations have been applied.
- API fails to load settings: generate three distinct keys, each at least 32 characters.
- UI cannot reach API: start the API and check `API_BASE_URL` (default `http://127.0.0.1:8000`).
- Port in use: stop the existing service or change its port and matching API URL.

## Explain this milestone in an interview

“An email becomes one case with a unique source identifier. Every customer question is stored separately. A transaction commits the case, questions, and audit event together. API role checks enforce read-only auditor access, and a database unique constraint prevents duplicate intake even when two requests race.”

## Milestone 3

Follow [the service deadline and NFCR walkthrough](MILESTONE_3.md) after verifying the local setup. Automatic deadline checks require the separate worker process. Existing closed cases keep their history without backdated service clocks.
