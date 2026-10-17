# PostTech web portal

The React + TypeScript portal follows the supplied green/white PostTech layouts, with a persistent sidebar, responsive navigation, dashboard, two-step request forms, and calendars. All live business operations go through `/api/v1`; the browser never receives server-side Supabase or OpenAI keys.

## Start locally

Start the API from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Start the frontend in another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies API requests to `http://127.0.0.1:8000`; set `API_PROXY_TARGET` in `frontend/.env.local` if the backend uses another address. See `frontend/.env.example`. Relative `/api/v1` is the recommended browser API URL, so no CORS configuration is needed for either local proxying or the combined build.

For one server, run `npm run build` inside `frontend`, then restart FastAPI and open `http://localhost:8000`. `docker compose up --build` builds both parts automatically using the committed npm lockfile. Refreshing a deep link such as `/requests/new` works; unknown `/api` and `/assets` paths remain HTTP 404 responses. Swagger stays at `/docs`.

## Accounts and demonstration

Real login and registration use Supabase Auth through the backend. Registration follows invitation → account → email verification → welcome. HR issues invitations from the employee directory and supplies the role, email and reporting manager; verified activation creates the HR profile atomically. Existing confirmed accounts can complete activation with their password. OTP accepts 6–8 digits, including paste/autofill, and resend has a 60-second cooldown. The optional remember checkbox stores only the email; passwords are never persisted. See [registration setup and verification](registration.md). Self-service password reset, SSO, and two-factor authentication are not implemented; the password-help dialog directs the employee to HR.

The **Демо-вход** button starts a walkthrough using fictional invitation `JP-DEMO-2026`. Select **Продолжить**, then **Создать аккаунт**; the invitation and sample account fields are already filled. Enter `472916` in **Код подтверждения**; the code is checked automatically and opens **Выберите роль**. Choose employee, manager or HR, select **Продолжить**, and then **Перейти на главную**. The demo workspace uses fictional data and mutations, is marked by a persistent banner, and stores changes in memory. Refreshing the tab restores the selected demo role but resets demonstration business data. Demo request drafts are scoped to that role and tab. No demo action calls a production service or changes real employee data. Signing out allows choosing another role or entering a real account.

Live access and refresh tokens are held in memory and this tab's `sessionStorage`, with a shared refresh operation for simultaneous requests. Logging out clears that session. Requests in flight cannot be retried as a newly selected account. The backend remains the authority for permissions.

## Available workflows

| Screen | Connected operations |
| --- | --- |
| Home / services | Own balance, recent requests, assigned courses, notifications, links to workflows |
| Requests | Own/review views, route preview and snapshot, search, type/status filters, pagination, leave/advance creation, review with rejection reason, owner withdrawal and history |
| Request form | Parameters, validation, tab-local draft, confirmation, idempotent submission, success and detail screens |
| Calendar | Month navigation, leave events from real requests, own/team view, day details, date range selection |
| Jana Academy | Catalog/own/team learning, course category/audience, material acknowledgement, threshold, failed attempts/retry, scored history and team results |
| AI Jana | Questions, grounded answers, openable authenticated source documents, unsupported-question/HR escalation state |
| Notifications / activity | Paginated events, unread filtering, mark read, links to related requests |
| Profile | Read-only official employee details and vacation balance |
| Team | Manager/HR employee list, profile details, course assignment and scoped learning overview |
| Settings | Local compact layout preference and sign out |

Request status reflects the API decision. Approval does not deduct the displayed vacation balance or create a signed document. Calendar entries represent leave requests; production shifts, statutory holidays, payroll dates, and legal restrictions are not invented. Attachments, electronic signatures, recall of approved leave, certificate generation, real 1C/Documentolog synchronization, and Kazakh localization require backend/product work and are not shown as functioning services.

## Checks

```powershell
cd frontend
npm run build
npm test
npm run test:e2e
```

The browser checks require Playwright Chromium (`npx playwright install chromium` if missing). They exercise demo workflows and browser-to-API contracts with controlled responses. They do not certify a configured Supabase environment. Run `python -m pytest` from the repository root for backend checks; real database checks remain opt-in as documented in the root README.

For an end-to-end check against a prepared Supabase project: sign in as the seeded employee, submit leave, sign in as their manager, review the request, then return to the employee account and verify its status, history, calendar, and notification. Also complete an assigned course and check the stored result. The UI is responsive, keyboard accessible, and respects reduced-motion preferences.

The compact live login form uses work email and password; the authenticated profile determines access. Managers and HR retain personal requests and learning alongside a separate work queue. Returning to the tab refreshes page data; notification links distinguish own courses from team course results. Quiz retry identifiers are preserved in tab storage until a result is acknowledged.


## UI refresh — 16 October 2026

The refreshed interface follows the supplied desktop/mobile reference: a pale canvas, white cards, green primary actions, dark text, and restrained blue/purple accents. The home screen places leave balance, quick actions, recent events and a real month calendar together. Managers and HR get a compact work queue. Only real profile balances and request dates are displayed; there is no invented annual entitlement or company event schedule.

Mobile navigation provides Home, Requests, Calendar and Profile. The remaining sections are available in the drawer; Settings is also linked from Profile. Request actions sit above the bottom navigation, including safe-area padding. Date selection opens the review screen directly; extra policy text is in a disclosure. Academy, profile and Jana use shorter copy and grouped information. Reduced-motion and keyboard focus styles remain available.

Secondary pages are loaded as separate route chunks. The initial stylesheet uses the system font stack and no longer waits for a remote font import. Dashboard no longer fetches a duplicate unread-notification count. The final build and existing client tests are checked after the visual update; the supplied Playwright specifications were updated for the new labels and review flow. Interactive visual checks use the browser with the real rendered interface.


Validation of this refresh: production build and all 19 client tests passed. The main JavaScript artifact is 367.04 kB (112.50 kB gzip), compared with 475.34 kB (136.88 kB gzip) before route splitting. Visual checks covered desktop home, mobile home/profile/Academy/Jana and the calendar → review → sent → request history flow in isolated demo mode. At 390 px, home and request review had no horizontal overflow. The built portal also loaded the real manager's Supabase data. Browser checks were interactive; the updated Playwright specifications were type-checked but not executed in this refresh. Desktop evidence is `.local/ui-refresh-desktop.jpg`.

## First delivery batch — 17 October 2026

The latest refinement makes the mobile balance card and four quick actions more compact. Manual calendar dates sit in a disclosure, selected-day totals use short labels, and profile sections become expandable rows through 900 px. The desktop sidebar starts at 901 px, matching the component behavior and stylesheet. Touch controls retain at least 44 px targets.

Forgot-password now has email, code/new-password, and success steps backed by the public recovery API. Codes support six or eight digits, resend has a cooldown, and a successful change returns to manual sign-in. The invitation recovery path keeps its email fixed. The interface uses a neutral email response; SMTP delivery remains pending. See [registration](registration.md) for provider configuration and limitations.

Validation: production build and **26 client tests passed**. Interactive checks covered a real employee's mobile leave submission, manager approval on desktop, and the employee's resulting notification/history, plus actual course results and an openable Jana source. Profile and recovery were inspected at 320 px, request submission at 390 px, home at 900 px, and the desktop flow at 1280 px. Details and evidence are in [live verification](live-verification.md). Existing E2E specifications were updated and type-checked, not run automatically in this batch.
