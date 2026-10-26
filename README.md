# Sentinel — AI Agent Governance & Monitoring

Sentinel is a local, synthetic-data demo platform for governing an AI loan
agent. It combines the repository's existing loan agent and policy rules with
a FastAPI API, PostgreSQL audit store, signed human approvals, deterministic
monitoring, and a React operations console. It does not approve real loans or
connect to a financial institution.

## Architecture

```text
React + TypeScript + Vite
        │ JSON API + authenticated SSE (same-origin Nginx proxy)
        ▼
FastAPI ── existing LoanAgent + centralized config/policies.yaml
        │ structured events, approval decisions, alerts
        ▼
SQLAlchemy 2.x ─ Alembic ─ PostgreSQL (persistent Docker volume)
```

- The current loan agent remains the policy enforcement boundary. Loans below
  INR 1,000 can be auto-approved; loans of INR 1,000 or more create a pending
  human approval request.
- The API adapts the existing agent's structured events into PostgreSQL rows.
  Existing deterministic governance detectors are reused to evaluate those
  event records. Alert evidence links back to the persisted event IDs.
- Human decisions are authorized from the authenticated user's database role,
  serialized into canonical JSON, signed with server-side HMAC-SHA256, and
  verified before the loan agent records its final outcome.
- The frontend obtains a short-lived JWT and keeps it in tab-scoped
  `sessionStorage`; API and SSE routes validate the token on the server.
- Compose runs one API worker. Its authenticated in-process SSE broadcaster is
  appropriate for this single-instance demo; use PostgreSQL `LISTEN/NOTIFY` or
  Redis before running multiple API workers.

## Repository layout

```text
agents/                  Existing loan, task, and data agents
config/policies.yaml     Central loan, duration, and resource policies
governance/              Existing event schema, monitor, and detectors
backend/app/              FastAPI routers, SQLAlchemy models, security, workflows
backend/alembic/          PostgreSQL migration history
frontend/src/             React pages, API client, and console styles
tests/                    Existing POC tests and platform security/API tests
docker-compose.yml        Frontend + API + PostgreSQL services
main.py, demo.py          Existing CLI POC entry points
```

## Technology

- **Web:** React 18, TypeScript, Vite, React Router, Tailwind CSS, Axios
- **API:** Python, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic
- **Data/security:** PostgreSQL, Argon2 password hashes, JWT access tokens,
  HMAC-SHA256 approval signatures
- **Deployment:** Docker Compose, Nginx static frontend/reverse proxy
- **Tests:** pytest; PostgreSQL-backed API tests use a separately named test DB

## Prerequisites

- Docker Engine and Docker Compose v2
- OpenSSL for generating local signing keys
- Optional for local-only development/tests: Python 3.12+ and Node.js 20+

## Configure and start

1. Copy the safe template and generate **two different** secrets:

   ```bash
   cp .env.example .env
   openssl rand -hex 32
   openssl rand -hex 32
   ```

   Put the first output in `JWT_SECRET`, the second in
   `APPROVAL_SIGNING_SECRET`. Replace `POSTGRES_PASSWORD` and both seed
   passwords with unique local values (at least 12 characters for the demo
   accounts). Do not commit `.env`. `DATABASE_URL` is optional; by default the
   API constructs it from the `POSTGRES_*` variables.

2. Build and start all services:

   ```bash
   docker compose config --quiet
   docker compose up --build -d
   docker compose ps
   ```

   The API waits for PostgreSQL health, applies `alembic upgrade head`, seeds
   the two demo users, then starts FastAPI. The frontend waits for the API
   health check. Default host ports are configurable in `.env`:

   - Web console: <http://localhost:3000>
   - FastAPI: <http://localhost:8001>
   - OpenAPI / Swagger UI: <http://localhost:8001/docs>
   - PostgreSQL (loopback-only, for local test tooling): port `55432`

   If a host port is already in use, set `FRONTEND_HOST_PORT`,
   `BACKEND_HOST_PORT`, or `POSTGRES_HOST_PORT` to an available port. The
   browser uses the Nginx `/api` reverse proxy, including for SSE.

3. Check health and seed state:

   ```bash
   curl http://localhost:8001/api/health
   docker compose logs --tail=80 backend
   ```

   Health returns `{"status":"ok","database":"connected"}` when the DB
   connection works.

## Migrations and demo users

Compose deliberately applies migrations before serving requests. To apply them
manually after a schema update:

```bash
docker compose exec backend alembic -c /app/backend/alembic.ini upgrade head
```

Seed creation is idempotent and uses the password values from `.env`:

```bash
docker compose exec backend python -m app.seed
```

Demo account emails are `approver@example.com` and `viewer@example.com`. Their
passwords are the values configured by `SEED_APPROVER_PASSWORD` and
`SEED_VIEWER_PASSWORD` in your local `.env`; no demo password is committed in
the repository.

## Use the console

### Overview and applications

Sign in as the approver to submit a synthetic loan application. The dashboard
metrics and recent records are read from PostgreSQL; empty databases show
zeroes and empty states.

- Submit **INR 500** or **INR 999**: the existing loan agent evaluates policy
  and automatically approves the request.
- Submit **INR 1,000** or **INR 2,000**: the agent records the request and
  human-approval-required events. The application stays pending in the queue.
- Application details show the real chronological workflow and any decision.

### Human approval and signatures

Open **Approval queue**, choose an application, and enter a non-empty reason
before approving or rejecting. The backend obtains the approver ID from the
verified JWT/user record, locks the pending request in PostgreSQL, stores one
decision per application, and records the decision in the execution timeline.

The canonical UTF-8 JSON payload includes decision ID, application ID,
decision, reason, approver ID, and UTC timestamp. The API signs it using
HMAC-SHA256 with `APPROVAL_SIGNING_SECRET`, stores the payload and signature,
then verifies the signature before it tells the loan agent to finalize. HMAC
verification uses the **same server-side secret**; the secret is never sent to
the frontend. This signature protects the integrity/authenticity of the
decision record and does not replace the independent approver-role check.

### Alerts and SSE

Open **Live alerts** to load existing alert records, filter by severity, rule,
agent, or status, and sort by time/severity. The authenticated SSE connection
streams committed new alerts; it reconnects after interruption and reloads
persisted alerts to cover a disconnection gap. Select an alert to inspect the
linked events and navigate to the execution timeline.

### Agents and execution timelines

Open **Agents & executions** to inspect agent identities and database-backed
execution records. Select an execution to see all its events in timestamp
order, inspect structured payloads, and identify evidence linked to alerts.
Policy findings are highlighted without hiding normal events.

## Run controlled governance scenarios

Scenario controls are approver-only and invoke actual backend workflows.
Deliberate misbehavior is an isolated test fixture; it cannot finalize an
unauthorized loan or grant resource access.

1. **Normal automatic approval:** submits INR 500 and confirms approval with
   no bypass alert.
2. **Human-in-the-loop:** submits INR 2,000 and confirms that it stays pending.
   Complete the demonstration by opening the approval queue, deciding with a
   reason, and inspecting the signed result and full timeline.
3. **Approval bypass attempt:** the test fixture asks the real loan agent to
   approve INR 2,000 without authorization. The agent blocks the attempt; the
   independent monitor emits a high-severity alert with linked evidence.
4. **Abnormal duration:** records a simulated 10-second task against the
   configured 300-second baseline and duration threshold. Both the execution
   and alert identify the measurement as simulated.
5. **Unauthorized resource:** the test agent requests
   `restricted_credit_records`. The backend compares it with the configured
   `data-agent` allowlist and denies it at the resource boundary before the
   monitor creates the evidence-backed alert.

Every run returns its measured pass/fail result, actual evidence event IDs,
execution ID, and related alert IDs. Open those links from the scenario result
to inspect persisted records.

Duration policy lives in `config/policies.yaml`; `ANOMALY_THRESHOLD_SECONDS`
can override the threshold (default 60 seconds). The 10-second example is a
deterministic **simulated test measurement**, not a production timing claim.
The controlled resource allowlist is also in `config/policies.yaml`.

## Authentication and authorization

- `/api/auth/login` validates credentials against Argon2 password hashes and
  issues an expiring JWT. `/api/auth/me` returns the active database-backed
  role. Logout clears the tab's access token; tokens are short lived and there
  are no refresh tokens.
- Viewer and approver roles can read dashboards, alerts, applications,
  evidence, and timelines. Only an approver can submit/decide applications,
  change alert status, or run privileged scenarios.
- These checks are enforced by FastAPI dependencies, not just frontend
  controls. A viewer calling a decision endpoint directly receives HTTP 403.
- In production mode, the API refuses to start if the JWT or approval signing
  key is missing/short. Keep secrets in environment configuration, not in
  frontend build variables.

## API reference

FastAPI OpenAPI schema is at `/openapi.json`; interactive docs are at `/docs`.
Main routes (all except login and health require a bearer token):

| Route | Purpose |
|---|---|
| `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` | JWT session |
| `GET /api/dashboard` | Persistent metrics and recent records |
| `GET, POST /api/applications` | List/search or submit a loan |
| `GET /api/applications/{id}` | Application, signed decision, and events |
| `GET /api/approvals` | Pending human decisions |
| `POST /api/applications/{id}/decision` | Approver-only signed decision |
| `GET /api/alerts`, `GET /api/alerts/{id}` | Filtered alerts and evidence |
| `PATCH /api/alerts/{id}` | Approver acknowledges/resolves an alert |
| `GET /api/alerts/stream` | Authenticated SSE alert feed |
| `GET /api/agents`, `GET /api/executions` | Monitored agents and runs |
| `GET /api/executions/{id}` | Chronological timeline and related alerts |
| `GET /api/executions/{id}/events` | Paginated execution events |
| `POST /api/scenarios` | Approver-only controlled test execution |

Alert and event list endpoints support bounded pagination. API request errors
use FastAPI's structured `detail` response.

## Tests and development

Install project dependencies and run the existing POC regressions plus platform
unit/security tests:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

The PostgreSQL integration test is skipped unless `TEST_DATABASE_URL` points
to a dedicated PostgreSQL database named `*_test`. It drops/recreates tables
in that database, so **never point it at demo or production data**. With the
Compose database running, create the test DB once and run:

```bash
set -a
. ./.env
set +a
docker compose exec -T db sh -c 'createdb -U "$POSTGRES_USER" "${POSTGRES_DB}_test"'
TEST_DATABASE_URL="postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@127.0.0.1:${POSTGRES_HOST_PORT:-55432}/${POSTGRES_DB}_test" \
  pytest -q tests/test_platform_api.py
```

To run the React production type check/build:

```bash
cd frontend
npm ci
npm run build
npm audit
```

The Vite development server can be used for frontend iteration with the FastAPI
API running on `localhost:8000`. When using the Compose API host mapping, set
the proxy target to `localhost:8001`:

```bash
cd frontend
VITE_API_PROXY_TARGET=http://localhost:8001 npm run dev
# Or use the default target for a directly launched API on port 8000:
npm run dev
```

The original command-line POC remains available:

```bash
python main.py demo
python main.py demo --mode faulty
python main.py watch --pace 1.2
python main.py test
python main.py report
```

## Persistence and troubleshooting

- PostgreSQL data is stored in the `postgres_data` named volume and survives
  container recreation. `docker compose down` preserves it; `docker compose
  down -v` deletes it.
- If a container is unhealthy, inspect `docker compose ps` and
  `docker compose logs backend db`. The backend only starts after PostgreSQL
  passes `pg_isready`.
- If Compose reports a missing secret/password, replace the placeholders in
  `.env`; do not remove required-secret checks or use the template values.
- If a host port is taken, change the corresponding `*_HOST_PORT` variable in
  `.env`, then recreate with `docker compose up --build -d`.
- If migrations fail, inspect the Alembic error before retrying. Do not delete
  the persistent DB volume to mask a migration error.
- If the live feed says disconnected, check `/api/health`, the browser network
  request to `/api/alerts/stream`, and Nginx/API logs. The feed requires an
  authenticated browser session.

## What is real and what is simulated

Real in this local app: the repository's `LoanAgent` policy enforcement,
persisted user/application/execution/event/approval/alert records, API role
checks, canonical HMAC signature and verification, deterministic monitoring
detectors, and authenticated SSE delivery after database commit.

Synthetic/controlled: applicant records, data-access target, abnormal-duration
measurement, and deliberate bypass agent. The bypass fixture is blocked by the
same loan-agent enforcement boundary and cannot become a valid approval.
No AWS service, financial network, external AI model, or actual restricted
resource is connected by the web platform. The legacy CLI still has its
optional SNS/CloudTrail extensions, but the local web deployment does not
require AWS.

## Local-demo security limitations

This is a technical demonstration, not a production financial service. It
uses a shared-secret HMAC key and one API worker, has no TLS by default, no
refresh-token/revocation store, no production user provisioning or rate
limiting, and stores a short-lived bearer token in tab-scoped browser storage.
Use synthetic data, protect `.env`, use unique passwords, and place production
deployments behind TLS, hardened secret management, centralized identity,
monitoring, and a multi-worker event broker.

## Existing POC demo media

![Existing governance POC walkthrough](docs/assets/demo.gif)

[Open the original demo video](docs/assets/demo.mp4)
