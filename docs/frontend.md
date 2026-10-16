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

Real login and registration use Supabase Auth through the backend. Complete the Supabase setup in the root README before signing in. HR must link registered accounts to `employee_profiles`; registration never grants a role. Email-confirmation and unlinked-profile states are shown in the portal. Self-service password recovery, SSO, and two-factor authentication are not implemented by the current API; the recovery dialog directs the employee to their administrator.

The explicit **Открыть демоверсию** button opens an isolated demo account as employee, manager, or HR. Data and mutations are fictional, marked by a persistent banner, and stored in memory. Refreshing the tab restores the selected demo role but resets demonstration business data. Demo request drafts are scoped to that role and tab. No demo action calls a production service or changes real employee data. Signing out allows choosing another role or entering a real account.

Live access and refresh tokens are held in memory and this tab's `sessionStorage`, with a shared refresh operation for simultaneous requests. Logging out clears that session. Requests in flight cannot be retried as a newly selected account. The backend remains the authority for permissions.

## Available workflows

| Screen | Connected operations |
| --- | --- |
| Home / services | Own balance, recent requests, assigned courses, notifications, links to workflows |
| Requests | Own/team views, search, type/status filters, pagination, leave/advance creation, review, request history |
| Request form | Parameters, validation, tab-local draft, confirmation, idempotent submission, success and detail screens |
| Calendar | Month navigation, leave events from real requests, own/team view, day details, date range selection |
| Jana Academy | Catalog, assigned courses, material, progress, quiz and server-calculated score |
| AI Jana | Questions, grounded answers, cited sources, unsupported-question/HR escalation state |
| Notifications / activity | Paginated events, unread filtering, mark read, links to related requests |
| Profile | Read-only official employee details and vacation balance |
| Team | Manager/HR employee list, profile details, course assignment |
| Settings | Local compact layout preference and sign out |

Request status reflects the API decision. Approval does not deduct the displayed vacation balance or create a signed document. Calendar entries represent leave requests; production shifts, statutory holidays, payroll dates, and legal restrictions are not invented. Attachments, electronic signatures, cancellation, certificate generation, real 1C/Documentolog synchronization, and Kazakh localization require backend/product work and are not shown as functioning services.

## Checks

```powershell
cd frontend
npm run build
npm test
npm run test:e2e
```

The browser checks require Playwright Chromium (`npx playwright install chromium` if missing). They exercise demo workflows and browser-to-API contracts with controlled responses. They do not certify a configured Supabase environment. Run `python -m pytest` from the repository root for backend checks; real database checks remain opt-in as documented in the root README.

For an end-to-end check against a prepared Supabase project: sign in as the seeded employee, submit leave, sign in as their manager, review the request, then return to the employee account and verify its status, history, calendar, and notification. Also complete an assigned course and check the stored result. The UI is responsive, keyboard accessible, and respects reduced-motion preferences.
