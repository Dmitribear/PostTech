# PostTech Digital HR MVP

FastAPI REST backend for the JanaMen Digital HR hackathon prototype. The MVP demonstrates one employee journey across profile, HR requests, Jana Academy, notifications, and AI Jana, with worker/manager/HR role enforcement.

The React web portal in `frontend/` connects the supplied PostTech layouts to the API: sign in, inspect the read-only profile, submit a request, review it as the employee's manager or HR, inspect its history, and read notifications. It also includes a leave calendar, Jana Academy with quizzes, AI Jana, and team management. Follow the [frontend guide](docs/frontend.md), the [step-by-step API guide](docs/leave-workflow.md), or the [HTTP examples](examples/leave-workflow.http).

## Architecture

- `app/main.py` creates the FastAPI application; `/api/v1` is the versioned API boundary.
- `app/api/routes/` contains HTTP endpoints. `app/core/security.py` validates Supabase Auth access tokens and resolves the user's HR role.
- `app/core/permissions.py` applies ownership and manager-team checks before returning or changing employee data.
- `app/db/supabase.py` creates the server-side Supabase client; `app/services/` contains application operations.
- `database/migrations/0001_digital_hr.sql` defines the MVP schema and enables RLS. `0002_request_workflow.sql` adds request history and transactional create/review operations. `database/seed.sql` adds fictional demo content and records.
- Request flow: client -> bearer-token validation -> role/ownership checks -> API route/service -> Supabase Postgres/Auth.

## Implemented API

HR endpoints require a Supabase Auth bearer access token. `/`, `/api/v1/health/*`, and `/api/v1/auth/register`, `/login`, `/refresh` do not require an existing access token; refresh requires a refresh token in its body.

| Endpoint | Purpose and access |
| --- | --- |
| `POST /api/v1/auth/register` | Register email/password in Supabase Auth. Email confirmation may be required; HR must link the Auth account to an employee profile before it can use HR endpoints. |
| `POST /api/v1/auth/login` | Sign in and receive `access_token` and `refresh_token`. |
| `POST /api/v1/auth/refresh` | Exchange a refresh token for a new session. |
| `GET /api/v1/profile` | Current user's read-only HR profile. |
| `GET /api/v1/employees/{employee_id}` | Own profile; managers can view direct reports; HR can view all. |
| `GET /api/v1/team` | Direct reports for managers; all profiles for HR. |
| `GET /api/v1/requests` | View permitted requests; filter by `employee_id`, `status`, or `request_type`; paginate with `limit` (default 50, max 100) and `offset` (default 0). |
| `POST /api/v1/requests` | Create a leave or advance request for the current employee; optional UUID `Idempotency-Key` prevents duplicate submission. |
| `GET /api/v1/requests/{id}` | Read a request only if its employee profile is visible to the caller. |
| `GET /api/v1/requests/{id}/history` | View request events with the same employee access checks as the request itself. |
| `PATCH /api/v1/requests/{id}/review` | The employee's manager or HR can approve/reject a pending request. Self-review is forbidden for all roles. An identical retry by the same reviewer returns the existing decision. |
| `GET /api/v1/academy/courses` | Active course catalog with the current user's assignment state. |
| `GET /api/v1/academy/my-courses` | Assigned courses and progress. |
| `GET /api/v1/academy/courses/{id}` | Course material and quiz; quiz answers are never returned. |
| `POST /api/v1/academy/assignments` | HR or the employee's manager assigns a course. |
| `PATCH /api/v1/academy/courses/{id}/progress` | Save course progress. |
| `POST /api/v1/academy/courses/{id}/complete` | Submit quiz answers; the API calculates and stores the score. |
| `GET /api/v1/notifications` | Current user's notifications only; optional UUID `request_id`, `unread_only` (default `false`), `limit` (default/max 100), and `offset` (default 0). |
| `POST /api/v1/notifications/{id}/read` | Mark an own notification as read; UUID required. Retries return the original `read_at`; another user's notification returns `404`. |
| `POST /api/v1/ai/ask` | Jana answers from retrieved knowledge articles, returns sources, or refuses and suggests HR escalation. |

Roles are `worker`, `manager`, and `hr_admin`. Official profile data is read-only. Database row-level security is enabled; direct public-key browser access is denied by default. The backend uses the server-side Supabase key and enforces access in the API, so that key must never be exposed to a client.

The server derives the role from the linked employee profile. A role selected in a client or supplied in a request cannot grant additional permissions. Creation and review each save the request, its history event, and the corresponding notifications in one database transaction. Responses do not expose the internal idempotency key.

## Supabase setup and demo data

1. Create a Supabase project and copy `.env.example` to `.env`.
2. Set `SUPABASE_URL`, the server-side `SUPABASE_KEY`, and the project's public `SUPABASE_ANON_KEY` in `.env`. The anon key is used only by the backend's Supabase Auth signup/login client; keep the server key private and never commit `.env`. Optionally set `OPENAI_API_KEY` and `OPENAI_MODEL` for generated Jana responses; without the key Jana returns matched source excerpts instead.
3. For a new database, run [0001_digital_hr.sql](database/migrations/0001_digital_hr.sql), then [0002_request_workflow.sql](database/migrations/0002_request_workflow.sql) in the Supabase SQL editor, in that order. For an existing database that already has `0001`, apply only `0002`; do not rerun `0001`. Starting the API does not apply migrations automatically.
4. In Supabase Auth, create fictional test users with emails `hr@posttech.demo`, `manager@posttech.demo`, and `employee@posttech.demo`. Set local demo passwords in Supabase; no credentials are stored in this repository.
5. Run [database/seed.sql](database/seed.sql). It creates fictional profiles, two courses, knowledge articles, course assignments, and sample requests with history/notifications. It uses no real employee data.
6. Sign in as each seeded user through `POST /api/v1/auth/login` with the password set in step 4. Send the returned `access_token` as `Authorization: Bearer <token>` to protected API routes. Keep tokens and demo passwords in your local HTTP-client environment, outside version control. To issue a refreshed session, send its `refresh_token` to `POST /api/v1/auth/refresh`.
7. For an additional account, register through `POST /api/v1/auth/register` and confirm the email if required. An administrator must create or link its HR profile through the Supabase SQL editor; registration itself does not create an employee profile or accept a role. See the [account-linking instructions](docs/leave-workflow.md#подготовка-учётных-записей). Without a linked profile, protected HR endpoints return `403`.

## Run

With `.env` configured and demo SQL applied, run `docker compose up --build`. The multi-stage image builds and serves the web portal at `http://localhost:8000`, with API routes under `/api/v1` and Swagger UI at `http://localhost:8000/docs`.

The API container can start without `.env`, but Supabase-dependent endpoints will not work until valid credentials are provided. `GET /api/v1/health/live` checks process liveness. `/api/v1/health/ready` checks whether Supabase client configuration can be initialized; it does not prove that a database query succeeds.

For local development, use Python 3.12+, install `requirements-dev.txt`, and run `uvicorn app.main:app --reload`. The Docker image uses Python 3.12.

For frontend development, use Node.js 22+, then run `npm ci` and `npm run dev` from `frontend/`. Open `http://localhost:5173`; `/api` is proxied to `http://127.0.0.1:8000`. `npm run build` creates `frontend/dist`, which FastAPI serves after its next startup. If no build exists, `/` keeps the API information response. The login screen offers an explicit, isolated demo mode for all three roles; it does not contact Supabase or fall back to demo after a failed real login.

## Scope and integration boundary

- **Implemented:** role-aware profile reads, leave/advance requests with history and retry protection, manager/HR review, notifications, assigned learning with server-side quiz scoring, and source-grounded Jana Q&A/refusal.
- **Mocked:** employee records are seeded snapshots marked `mock-1c-zup`; courses and HR policy articles are fictional demo data.
- **Not connected yet:** live 1C:ЗУП and Documentolog integrations. Replace the profile snapshot source with a read-only 1C adapter and add a Documentolog adapter behind service boundaries; do not let either integration make employee-editable official data.
- **Not included:** production HR policies, real employee data, electronic signatures, original document storage, recruiting, or AI-driven personnel decisions.

Approving a leave request records the decision in this prototype. It does not deduct vacation days, update 1C, or issue a Documentolog document. Vacation balance stays a read-only profile value. Date validation requires both dates and an end date on or after the start date; past dates, holiday calendars, overlap rules, and a required notice period are not invented as HR policy. The schema includes `cancelled` for filtering, but this workflow does not expose a cancellation operation.

## Tests

Install `requirements-dev.txt` and run `pytest`. The default API tests use local substitutes for external services. Real PostgreSQL tests are opt-in and skipped unless `POSTTECH_TEST_DATABASE_URL` is set. Neither test suite confirms that migrations are installed in your Supabase project; use the [manual leave workflow](docs/leave-workflow.md) against a prepared demo database to verify that full path.

To run the [database tests](tests/test_request_workflow_db.py), prepare an empty local PostgreSQL control database named `posttech_test_*` (for example, `posttech_test_control`). Use a local test administrator allowed to create databases and roles (`CREATEDB`, `CREATEROLE`), initialize the test `service_role` with `BYPASSRLS`, and `SET ROLE` to the test roles. A local PostgreSQL installation is sufficient; Docker and a Supabase account are not required. Then run in PowerShell, replacing the connection placeholders locally:

```powershell
python -m pip install -r requirements-dev.txt
python -m pip install -r tests/requirements-db.txt
$env:POSTTECH_TEST_DATABASE_URL = 'postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/posttech_test_control'
python -m pytest tests/test_request_workflow_db.py -q
Remove-Item Env:POSTTECH_TEST_DATABASE_URL
```

Tests create a separate `posttech_test_<UUID>` database, apply the real migrations there, and drop only that generated database afterward. They do not clear the control database or connect to a configured Supabase project. Missing cluster roles `anon`, `authenticated`, and `service_role` are created for the fixture and retained; existing roles are checked, not modified. Use a dedicated local test PostgreSQL instance and keep its connection credentials outside version control.
