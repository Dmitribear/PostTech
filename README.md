# PostTech Digital HR MVP

FastAPI REST backend for the JanaMen Digital HR hackathon prototype. The MVP demonstrates one employee journey across profile, HR requests, Jana Academy, notifications, and AI Jana, with worker/manager/HR role enforcement.

## Architecture

- `app/main.py` creates the FastAPI application; `/api/v1` is the versioned API boundary.
- `app/api/routes/` contains HTTP endpoints. `app/core/security.py` validates Supabase Auth access tokens and resolves the user's HR role.
- `app/core/permissions.py` applies ownership and manager-team checks before returning or changing employee data.
- `app/db/supabase.py` creates the server-side Supabase client; `app/services/` contains notification and Jana behavior.
- `database/migrations/0001_digital_hr.sql` defines the MVP schema and enables RLS. `database/seed.sql` adds fictional demo content and records.
- Request flow: client -> bearer-token validation -> role/ownership checks -> API route/service -> Supabase Postgres/Auth.

## Implemented API

All routes except `/` and `/api/v1/health/*` require a Supabase Auth bearer access token.

| Endpoint | Purpose and access |
| --- | --- |
| `POST /api/v1/auth/register` | Register email/password in Supabase Auth. Email confirmation may be required; HR must link the Auth account to an employee profile before it can use HR endpoints. |
| `POST /api/v1/auth/login` | Sign in and receive `access_token` and `refresh_token`. |
| `POST /api/v1/auth/refresh` | Exchange a refresh token for a new session. |
| `GET /api/v1/profile` | Current user's read-only HR profile. |
| `GET /api/v1/employees/{employee_id}` | Own profile; managers can view direct reports; HR can view all. |
| `GET /api/v1/team` | Direct reports for managers; all profiles for HR. |
| `GET, POST /api/v1/requests` | View permitted requests; create leave or advance requests. |
| `GET /api/v1/requests/{id}` | Read a request only if its employee profile is visible to the caller. |
| `PATCH /api/v1/requests/{id}/review` | Manager of the employee or HR can approve/reject pending requests. |
| `GET /api/v1/academy/courses` | Active course catalog with the current user's assignment state. |
| `GET /api/v1/academy/my-courses` | Assigned courses and progress. |
| `GET /api/v1/academy/courses/{id}` | Course material and quiz; quiz answers are never returned. |
| `POST /api/v1/academy/assignments` | HR or the employee's manager assigns a course. |
| `PATCH /api/v1/academy/courses/{id}/progress` | Save course progress. |
| `POST /api/v1/academy/courses/{id}/complete` | Submit quiz answers; the API calculates and stores the score. |
| `GET /api/v1/notifications` | Current user's notifications only. |
| `POST /api/v1/notifications/{id}/read` | Mark own notification as read. |
| `POST /api/v1/ai/ask` | Jana answers from retrieved knowledge articles, returns sources, or refuses and suggests HR escalation. |

Roles are `worker`, `manager`, and `hr_admin`. Official profile data is read-only. Database row-level security is enabled; direct public-key browser access is denied by default. The backend uses the server-side Supabase key and enforces access in the API, so that key must never be exposed to a client.

## Supabase setup and demo data

1. Create a Supabase project and copy `.env.example` to `.env`.
2. Set `SUPABASE_URL`, the server-side `SUPABASE_KEY`, and the project's public `SUPABASE_ANON_KEY` in `.env`. The anon key is used only by the backend's Supabase Auth signup/login client; keep the server key private and never commit `.env`. Optionally set `OPENAI_API_KEY` and `OPENAI_MODEL` for generated Jana responses; without the key Jana returns matched source excerpts instead.
3. Run [database/migrations/0001_digital_hr.sql](database/migrations/0001_digital_hr.sql) in the Supabase SQL editor.
4. In Supabase Auth, create fictional test users with emails `hr@posttech.demo`, `manager@posttech.demo`, and `employee@posttech.demo`. Set local demo passwords in Supabase; no credentials are stored in this repository.
5. Run [database/seed.sql](database/seed.sql). It creates fictional profiles, two courses, knowledge articles, course assignments, and sample requests/notifications. It uses no real employee data.
6. Register via `POST /api/v1/auth/register`, confirm the email if Supabase requires it, then sign in via `POST /api/v1/auth/login`. Send the returned `access_token` as `Authorization: Bearer <token>` to protected API routes. HR must link `user_id` from Auth to the employee's existing `auth_user_id` profile field; public registration never accepts a role or edits official employee data. To issue a refreshed session, send its `refresh_token` to `POST /api/v1/auth/refresh`.

## Run

With `.env` configured and demo SQL applied, run `docker compose up --build`. API: `http://localhost:8000`; Swagger UI: `http://localhost:8000/docs`.

The API container can start without `.env`, but Supabase-dependent endpoints will not work until valid credentials are provided. `GET /api/v1/health/live` checks process liveness. `/api/v1/health/ready` checks whether Supabase client configuration can be initialized; it does not prove that a database query succeeds.

For local development, use Python 3.12, install `requirements-dev.txt`, and run `uvicorn app.main:app --reload`.

## Scope and integration boundary

- **Implemented:** role-aware profile reads, leave/advance request workflow, manager/HR review, notifications, assigned learning with server-side quiz scoring, and source-grounded Jana Q&A/refusal.
- **Mocked:** employee records are seeded snapshots marked `mock-1c-zup`; courses and HR policy articles are fictional demo data.
- **Not connected yet:** live 1C:ЗУП and Documentolog integrations. Replace the profile snapshot source with a read-only 1C adapter and add a Documentolog adapter behind service boundaries; do not let either integration make employee-editable official data.
- **Not included:** production HR policies, real employee data, electronic signatures, original document storage, recruiting, or AI-driven personnel decisions.

## Tests

Install `requirements-dev.txt` and run `pytest`. Demo users and database tables are only needed for integration tests; the included health endpoint tests do not require Supabase credentials.
