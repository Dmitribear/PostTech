# PostTech Digital HR MVP

FastAPI REST backend for the JanaMen Digital HR hackathon prototype. The MVP demonstrates one employee journey across profile, HR requests, Jana Academy, notifications, and AI Jana, with worker/manager/director/HR role enforcement.

The React web portal in `frontend/` connects the supplied PostTech layouts to the API: sign in, inspect the read-only profile, submit a request, review it as the employee's manager or HR, inspect its history, and read notifications. It also includes a leave calendar, Jana Academy with quizzes, AI Jana, and team management. Follow the [frontend guide](docs/frontend.md), the [step-by-step API guide](docs/leave-workflow.md), or the [HTTP examples](examples/leave-workflow.http).

## Architecture

- Frontend: FSD (`app/pages/widgets/features/entities/shared`), Atomic UI primitives and checked import boundaries.
- Backend: `domain`, `application` (use cases/ports/DTO), `infrastructure`, `presentation`; `bootstrap.py` injects adapters.
- Transactional business commands remain in PostgreSQL; migrations `0001` through `0016` are the supported sequence.
- See [architecture and scaling constraints](docs/architecture.md) and [branch consolidation](docs/branch-consolidation.md).

## Implemented API

HR endpoints require a Supabase Auth bearer access token. Health, invitation check, registration/verification/activation, password login/recovery and refresh are public endpoints with their own input checks; refresh requires a refresh token in its body. Listing, issuing or revoking invitations requires HR authorization.

| Endpoint | Purpose and access |
| --- | --- |
| `POST /api/v1/auth/invitations/check` | Validate an HR invitation and obtain its bound email. |
| `POST /api/v1/auth/register` | Register with an invitation code, first/last name and password; the email and role come from HR. |
| `POST /api/v1/auth/verify-registration` | Verify the Supabase email OTP and atomically activate the invited HR profile. |
| `POST /api/v1/auth/resend-registration` | Resend confirmation, subject to server cooldown and provider limits. |
| `POST /api/v1/auth/complete-invitation` | Finish activation with an existing confirmed email/password; recover after a lost confirmation response. |
| `GET /api/v1/auth/invitations`, `POST /api/v1/auth/invitations`, `POST /api/v1/auth/invitations/{id}/revoke` | HR only: list, issue and revoke invitations. Codes are returned only at creation; only hashes are stored. |
| `POST /api/v1/auth/login` | Sign in and receive `access_token` and `refresh_token`. |
| `POST /api/v1/auth/password-reset` | Request a recovery code with a neutral response and 60-second resend delay; does not disclose account existence. |
| `POST /api/v1/auth/password-reset/confirm` | Verify a recovery code and set a strong password using only that user's isolated Auth session; returns no login tokens. |
| `POST /api/v1/auth/refresh` | Exchange a refresh token for a new session. |
| `GET /api/v1/profile` | Current user's read-only HR profile. |
| `GET /api/v1/employees/{employee_id}` | Own profile; managers can view direct reports; HR can view all. |
| `GET /api/v1/team` | Direct reports for managers/directors; all profiles for HR (legacy list). |
| `GET /api/v1/team/page` | Bounded keyset page: `limit` up to 100, `after` UUID, returns `items` and `next_cursor`. |
| `PATCH /api/v1/admin/employees/{id}/role` | HR-only audited role assignment with self-demotion/reporting-line guards. |
| `GET /api/v1/requests/{id}/calendar.ics` | Authorized export of approved leave, inclusive end date converted to ICS exclusive end. |
| `POST /api/v1/ai/local/ask` | Optional isolated local Jana provider; requires separately prepared models/reader. |
| `GET /api/v1/requests` | View permitted requests; filter by `employee_id`, `status`, `request_type`, and `scope=mine/review/all`; paginate with `limit` (default 50, max 100) and `offset` (default 0). |
| `POST /api/v1/requests` | Create a leave or advance request for the current employee; optional UUID `Idempotency-Key` prevents duplicate submission. |
| `GET /api/v1/requests/{id}` | Owner, eligible manager in the saved reviewer snapshot, or HR can read; a newly assigned manager does not automatically gain access to old requests. Full HR profile access remains independently restricted. |
| `GET /api/v1/requests/{id}/history` | View request events with the same employee access checks as the request itself. |
| `PATCH /api/v1/requests/{id}/review` | An assigned reviewer or HR can approve/reject a pending request. Rejection requires a reason. Self-review is forbidden for all roles. An identical retry by the same reviewer returns the existing decision. |
| `GET /api/v1/requests/routing` | Preview own approvers and submission policy. |
| `POST /api/v1/requests/{id}/cancel` | Owner withdraws a pending request; retries do not duplicate events. |
| `GET /api/v1/academy/team` | Manager sees direct reports’ learning; HR sees all assignments. Optional employee/course filters. |
| `GET /api/v1/academy/courses/{id}/attempts` | Own scored attempt history without answer keys. |
| `GET /api/v1/ai/sources/{id}` | Authenticated view of a published source. |
| `GET /api/v1/academy/courses` | Active course catalog with the current user's assignment state. |
| `GET /api/v1/academy/my-courses` | Assigned courses and progress. |
| `GET /api/v1/academy/courses/{id}` | Course material and quiz; quiz answers are never returned. |
| `POST /api/v1/academy/assignments` | HR or the employee's manager assigns a course. |
| `PATCH /api/v1/academy/courses/{id}/progress` | Save course progress. |
| `POST /api/v1/academy/courses/{id}/complete` | Submit after acknowledging material. UUID `Idempotency-Key` protects retries. Below the configured threshold the course remains in progress; a passing completion is immutable. |
| `GET /api/v1/notifications` | Current user's notifications only; optional UUID `request_id`, `unread_only` (default `false`), `limit` (default/max 100), and `offset` (default 0). |
| `POST /api/v1/notifications/{id}/read` | Mark an own notification as read; UUID required. Retries return the original `read_at`; another user's notification returns `404`. |
| `POST /api/v1/ai/ask` | Jana answers from retrieved knowledge articles, returns sources, or refuses and suggests HR escalation. |

Roles are `worker`, `manager`, and `hr_admin`. Official profile data is read-only. Database row-level security is enabled; direct public-key browser access is denied by default. The backend uses the server-side Supabase key and enforces access in the API, so that key must never be exposed to a client.

The server derives the role from the linked employee profile. A role selected in a client or supplied in a request cannot grant additional permissions. Creation and review each save the request, its history event, and the corresponding notifications in one database transaction. Responses do not expose the internal idempotency key.

## Supabase setup and demo data

1. Create a Supabase project and copy `.env.example` to `.env`.
2. Set `SUPABASE_URL`, the server-side `SUPABASE_KEY`, and the project's public `SUPABASE_ANON_KEY` in `.env`. The anon key is used only by the backend's Supabase Auth signup/login client; keep the server key private and never commit `.env`. Optionally set `OPENAI_API_KEY` and `OPENAI_MODEL` for model-selected, server-validated source excerpts; without the key Jana returns matched source excerpts instead.
3. Apply all SQL files in `database/migrations` in numeric order, currently **0001–0010**. On an existing project apply only missing migrations; inspect the current schema first. Starting the API does not apply SQL automatically. Migrations 0009–0010 add leave reservations, course lessons, the integration outbox and the HR knowledge editor. Existing completed courses and users are preserved; pending leave now reserves days. See the [operations guide](docs/operations-extensions.md) for migration boundaries, reconciliation and the disabled-by-default integration worker.
4. In Supabase Auth, create fictional test users with emails `hr@posttech.demo`, `manager@posttech.demo`, and `employee@posttech.demo`. Set local demo passwords in Supabase; no credentials are stored in this repository.
5. Run [database/seed.sql](database/seed.sql). It creates fictional profiles, two courses, knowledge articles, course assignments, and sample requests with history/notifications. It uses no real employee data. Optionally add [three detailed demo courses](database/seed_academy_demo.sql) after `0004`; this insert-only seed never overwrites existing content. After migration `0006`, apply [demo status guidance](database/seed_knowledge_status.sql), which refreshes only the named fictional status article.
6. Sign in as each seeded user through `POST /api/v1/auth/login` with the password set in step 4. Send the returned `access_token` as `Authorization: Bearer <token>` to protected API routes. Keep tokens and demo passwords in your local HTTP-client environment, outside version control. To issue a refreshed session, send its `refresh_token` to `POST /api/v1/auth/refresh`.
7. Apply `database/migrations/0005_registration_invitations.sql`. For additional employees, HR opens **Сотрудники → Пригласить сотрудника**, sets the email, role and reporting manager, and privately passes the generated code to that employee. The employee activates the invitation, creates an account and confirms the email. Profile creation and invitation consumption are atomic; the browser cannot select a real account's role. Configure SMTP and the confirmation template as described in the [registration guide](docs/registration.md). The first HR account still needs the [bootstrap linking procedure](docs/leave-workflow.md#подготовка-учётных-записей). Without a linked profile, protected HR endpoints return `403`.
8. Configure a mail provider and install the [signup](docs/templates/confirm-signup.html) and [password recovery](docs/templates/recovery.html) templates in Supabase. Both display `{{ .Token }}`. As of 17 October 2026, this project's Resend SMTP settings are saved and remain enabled after reload; a sending-only provider key and both Russian templates are installed, and their previews have been checked. The test sender `onboarding@resend.dev` can send only to the email associated with the Resend account; a verified domain is needed later for other recipients. The owner completed registration using the received eight-digit code: a confirmed Auth account, one worker profile and a consumed invitation were verified. Resend reports both signup and recovery emails as Delivered. **The owner also confirmed completing the password reset and signing in with the new password.** A final server read still found exactly one confirmed account, one worker profile and one consumed invitation. Earlier real Auth OTP checks passed without sending emails. A successful password-reset request is a neutral acceptance response, not a delivery receipt. See the [current verification status](docs/registration.md#статус-smtp--resend) and [test-domain restriction](https://resend.com/docs/knowledge-base/403-error-resend-dev-domain).

## Local jury stand

Open `Start PostTech.cmd` to run the prepared portal at **http://127.0.0.1:8010**; `Stop PostTech.cmd` stops its owned process. Internet is required for Supabase. See the [jury runbook](docs/jury-stand.md), [Jana evaluation](docs/jana-quality.md), and [5–6 minute defense script](docs/presentation/defense-script.md). Private jury credentials stay in `.local/jury-access.html`, outside Git and presentation files.

## Run

With `.env` configured and database migrations applied, open `Start PostTech Docker.cmd` or run `docker compose up --build -d --wait`. The launcher waits for a healthy container and opens **http://localhost:8000**. The multi-stage image builds the current frontend source and serves it together with the API under `/api/v1`; Swagger UI is at `http://localhost:8000/docs`.

Compose rebuilds the image on `docker compose up` (`pull_policy: build`). After changing source files, run the launcher again. Docker Desktop's Start/Restart button and `docker compose restart` only restart the existing container; they do not include new code. The separate non-Docker launcher `Start PostTech.cmd` uses port **8010**, so use port **8000** when checking Docker.

The API container can start without `.env`, but Supabase-dependent endpoints will not work until valid credentials are provided. `GET /api/v1/health/live` checks process liveness. `/api/v1/health/ready` performs a real knowledge-table read and verifies the columns introduced by migration 0006. Failures return a generic 503 without configuration details.

For local development, use Python 3.12+, install `requirements-dev.txt`, and run `uvicorn app.main:app --reload`. The Docker image uses Python 3.12.

For frontend development, use Node.js 22+, then run `npm ci` and `npm run dev` from `frontend/`. Open `http://localhost:5173`; `/api` is proxied to `http://127.0.0.1:8000`. `npm run build` creates `frontend/dist`, which FastAPI serves after its next startup. If no build exists, `/` keeps the API information response. The login screen offers an explicit, isolated demo mode for employee, manager and HR demo roles; it does not contact Supabase or fall back to demo after a failed real login.

## Scope and integration boundary

- **Implemented:** invitation registration, password login/recovery, role-aware profile reads, leave/advance requests with history and retry protection, manager/HR review, notifications, assigned learning with server-side quiz scoring, and source-grounded Jana Q&A/refusal.
- **Mocked:** employee records are seeded snapshots marked `mock-1c-zup`; courses and HR policy articles are fictional demo data.
- **Not connected yet:** live 1C:ЗУП and Documentolog integrations. Replace the profile snapshot source with a read-only 1C adapter and add a Documentolog adapter behind service boundaries; do not let either integration make employee-editable official data.
- **Not included:** production HR policies, real employee data, electronic signatures, original document storage, recruiting, or AI-driven personnel decisions.

Leave requests reserve days in a transactional ledger. Approval preserves the reservation; rejection or withdrawal releases it. Official balance is reconciled by HR against an external snapshot. Approval starts a separate HR document-fulfillment stage and does not claim that 1C or Documentolog has issued a document. The explicit prototype policy uses inclusive calendar dates and the Asia/Qyzylorda business date: past starts and overlaps with pending/approved leave are blocked. Owners can withdraw pending requests. Official entitlement, holiday calendars, notice periods, substitutes and recall of approved leave require a confirmed company policy and are not inferred. A manager’s own request goes to their eligible superior or HR; an HR employee cannot review their own request. With no eligible approver, submission is blocked with an explanation.

## Tests

Install `requirements-dev.txt` and run `pytest`. The default API tests use local substitutes for external services. Real PostgreSQL tests are opt-in and skipped unless `POSTTECH_TEST_DATABASE_URL` is set. Neither test suite confirms that migrations are installed in your Supabase project; use the [manual leave workflow](docs/leave-workflow.md) against a prepared demo database to verify that full path.

To run the [database tests](tests/test_request_workflow_db.py), prepare an empty local PostgreSQL control database named `posttech_test_*` (for example, `posttech_test_control`). Use a local test administrator allowed to create databases and roles (`CREATEDB`, `CREATEROLE`), initialize the test `service_role` with `BYPASSRLS`, and `SET ROLE` to the test roles. A local PostgreSQL installation is sufficient; Docker and a Supabase account are not required. Then run in PowerShell, replacing the connection placeholders locally:

```powershell
python -m pip install -r requirements-dev.txt
python -m pip install -r tests/requirements-db.txt
$env:POSTTECH_TEST_DATABASE_URL = 'postgresql://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/posttech_test_control'
python -m pytest tests/test_request_workflow_db.py tests/test_request_lifecycle_db.py tests/test_academy.py -q
Remove-Item Env:POSTTECH_TEST_DATABASE_URL
```

Tests create a separate `posttech_test_<UUID>` database, apply the real migrations there, and drop only that generated database afterward. They do not clear the control database or connect to a configured Supabase project. Missing cluster roles `anon`, `authenticated`, and `service_role` are created for the fixture and retained; existing roles are checked, not modified. Use a dedicated local test PostgreSQL instance and keep its connection credentials outside version control.

Latest consolidation verification (17 October 2026): **1119 backend tests passed**, including real PostgreSQL tests on isolated disposable databases. See [consolidation report](docs/branch-consolidation.md) for frontend checks and deployment prerequisites.

The guarded live recovery check creates only one uniquely marked fictional Auth account and sends no emails. It generates a real Supabase recovery OTP administratively, changes the password through the public application endpoint, rejects replay and the old password, verifies the new password, and checks revocation of the previous refresh session:

```powershell
.\.venv\Scripts\python.exe scripts/verify_password_recovery.py --live --project-ref zcsoipcwymhowmvnytxf
```

The explicit project reference must match the configured project; the API URL must be loopback. Retain the ignored `.local/recovery-credentials.json` checkpoint when retrying: the script validates its administrative fixture marker before any change. Existing employee and scenario accounts are never selected. The secret-free result is saved to `.local/recovery-verification.json`. The first live run passed 12 checks across 8 API calls; email delivery remains unverified. Password recovery has local per-email/IP limits in addition to Supabase limits; multiple API workers need a shared proxy limit.

## Role demonstration and evaluation

See the [role matrix and six-minute demo](docs/hackathon-scenarios.md), [architecture and integration boundaries](docs/architecture.md), and [live verification record](docs/live-verification.md). All demonstration accounts are fictional. `scripts/provision_scenario_accounts.py --project-ref zcsoipcwymhowmvnytxf` creates a repeatable seven-account hierarchy and writes passwords only to ignored `.local/scenario-credentials.json`; never publish that file. `scripts/verify_role_scenarios.py` exercises the installed API with this fixture and intentionally accepts only this test project. For another project, review and adapt the fixture guard before running it. The login uses one email/password form: the server chooses rights from the linked profile, while the separately labelled demo picker works entirely in memory.


## Stages 7–10

The subsequent [five HR workflow improvements](docs/hr-workflows.md) add HR document fulfillment, atomic CSV/XLSX employee import previews, sequential onboarding tracks, role-scoped Jana operational reports, and deduplicated reminders. Apply migrations 0011–0012 before rebuilding. The standard Compose stack now includes `workflow-worker`; direct Python launches need `python -m scripts.workflow_worker` in a separate process. Achievements/gamification are intentionally omitted.

The live stand now includes date-limited approval deputies, an HR course editor with immutable published versions, assignment deadlines, Russian/Kazakh UI and translated course content, and consent-based in-portal HR tickets. See [verification and boundaries](docs/stages-7-10.md). Run `python scripts/verify_workspace_live.py` only with the marked fictional jury/scenario fixtures; the checkpoint prevents duplicate submissions.

New authenticated API routes are under `/api/v1/workspace`: `/delegations`, `/courses`, `/assignments/{id}/deadline`, and `/tickets`. Only HR can administer deputies/course content or answer tickets. A manager's temporary approval right does not grant employee-profile or learning-management rights. `Accept-Language: kk` selects translated course content and notification labels; missing content translations are explicitly shown as Russian originals.
