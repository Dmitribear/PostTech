# PostTech web portal

The React + TypeScript portal follows the supplied green/white PostTech layouts, with a persistent sidebar, responsive navigation, dashboard, two-step request forms, and calendars. All live business operations go through `/api/v1`; the browser never receives server-side Supabase or OpenAI keys.

## Start locally

Start the API from the repository root:

```powershell
.\.venv\runtime\Scripts\python.exe -m uvicorn app.main:app --reload
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
| Calendar | Month navigation, leave events from real requests, own/team view, date range selection; approved request cards download ICS for manual import |
| Jana Academy | Catalog, assigned courses, material, progress, quiz and server-calculated score |
| AI Jana | Local semantic FAQ answers, authenticated source dialog with exact excerpt and full article, explicit refusal and service errors |
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

## Локальный ИИ во фронтенде без Supabase

Из корня репозитория запустите реальную локальную модель с вымышленной базой:

```powershell
.\.venv\runtime\Scripts\python.exe -m uvicorn examples.jana_local_demo:app --host 127.0.0.1 --port 8002
```

Если модель ещё не установлена, сначала выполните `python -m scripts.prepare_jana_local` в окружении с зависимостями проекта. Укажите в `frontend/.env.local`:

```dotenv
VITE_DEMO_JANA_PROXY=/jana-demo
```

В другом терминале запустите `npm run dev` из `frontend`. Откройте
`http://127.0.0.1:5173`, нажмите «Открыть демоверсию» → «Сотрудник» → «AI Jana».
Вопрос «Хочу уйти в отпуск, как подать заявку?» вызывает настоящий локальный
семантический поиск. Нажатие на источник показывает цитату и полный материал.
«Какая погода завтра?» проверяет отказ без источников. Учебные материалы явно
помечены: они не являются утверждёнными правилами JanaPost.

Данные сотрудников и заявки в этом режиме вымышлены и живут в памяти браузера.
ИИ и экспорт файла обращаются только к отдельному loopback-серверу через
`/jana-demo`. Токены рабочего HR-аккаунта и cookies туда не пересылаются.
Если сервер выключен, отображается ошибка; ответа по ключевым словам и платного
fallback нет. Без флага Jana в демоверсии отключена. В production-сборке этот
мост отключён независимо от флага; обычный вход использует защищённый API.

Для проверки файла откройте одобренную заявку на отпуск → «Скачать отпуск (.ics)».
Файл в демоверсии получает префикс «Демо:» и именно даты открытой заявки.
В рабочем режиме сервер сам читает даты одобренной заявки из БД, проверяет права
и возвращает файл по `GET /api/v1/requests/{uuid}/calendar.ics`.
Фронтенд отправляет Bearer-токен, при необходимости обновляет сессию и сохраняет
`text/calendar` как Blob. JSON-ошибки и HTML не выдаются за календарный файл.
Импорт в Google Calendar выполняется вручную; перенос и отмена автоматически
не синхронизируются. Реального импорта в аккаунт Google при проверке не делали.

## Совместимость веток

Проверенные версии: `Integration` — `5ac2cfb`, `origin/test` — `c274a31`,
`origin/ver2` — `f113562`. В рабочую копию Integration перенесены следующие части;
ветки друзей не изменены.

| Часть | Решение |
| --- | --- |
| React/Vite-портал из `test` | Подключён к `/api/v1`; типы Jana расширены полями `id`, `excerpt`, `mode`, добавлено чтение источника. |
| Заявки и уведомления из `test` | Перенесены вместе с UI: фильтры, пагинация, история, идемпотентность и транзакционные RPC нужны существующим экранам. |
| Локальная Jana и календарь из `Integration` | Сохранены; календарь использует проверку доступа из нового сервиса заявок. |
| Auth из `ver2` | Перенесено исправление: ошибка настройки регистрации остаётся 503; распознаются перепутанные ключи. |
| Альтернативный AI из `ver2` | Не используется: рабочий HTTP-агент остаётся локальным, без OpenAI. |
| Триггеры заявок и курсов из `ver2` | Не перенесены. Для курсов сохранён прежний сервис; объединение этого варианта БД требует отдельной миграции. |

У веток **несовместимые миграции 0002**:

- `test/0002_request_workflow.sql`: таблица `request_events`, поля `from_status` /
  `to_status`, события `created`, `approved`, `rejected`; RPC создают историю и
  уведомления в одной транзакции.
- `ver2/0002_atomic_workflows.sql`: таблица `hr_request_events`, поля `old_status` /
  `new_status`; триггер `hr_requests_record_events` сам создаёт историю и уведомления.

Если применить оба механизма, формат истории расходится и уведомления могут
дублироваться. Для этой интеграции выбран вариант `test`. Перед выполнением
миграции добавлена проверка триггера `ver2`: она прерывает транзакцию, ничего не
удаляя. Если `ver2` уже установлен в общей базе, сначала нужна отдельная миграция
перехода с сохранением истории; повторно выполнять 0001 или удалять таблицы нельзя.
Если исходный `test/0002` уже применён, повторно запускать его также не нужно.

Порядок для **новой демонстрационной базы**: `0001_digital_hr.sql` →
`0002_request_workflow.sql` → тестовые Auth-пользователи → `seed.sql` →
`seed_jana_demo.sql`. Реальные правила HR должны заменить учебные статьи и
согласованные FAQ по инструкции [локальной Jana](ai-jana-agent.md).

## Результаты проверки интеграции

На 17 октября 2026 года: сборка TypeScript/Vite успешна, 29 тестов клиента,
177 тестов Python и 24 браузерных сценария в Edge (desktop/mobile) прошли.
Браузерные автотесты используют контролируемые ответы API; отдельно вручную
проверен портал с настоящей локальной моделью: вопрос другими словами,
открытие источника и отказ на вопрос про погоду. Экспорт через настоящий Vite-прокси проверен HTTP-запросом и разбором ICS: однодневный отпуск 31 декабря заканчивается исключающей датой 1 января.

37 изолированных PostgreSQL-тестов пропущены: `POSTTECH_TEST_DATABASE_URL` не настроен.
Они не запускались на общем проекте команды.

## Проверка общего Supabase

17 октября 2026 года локальный портал подключён к проекту команды
`zcsoipcwymhowmvnytxf`. Настройки `SUPABASE_URL`, `SUPABASE_KEY` (серверный secret)
и `SUPABASE_ANON_KEY` (publishable) сохранены только в игнорируемом корневом
`.env`. Серверный ключ не передаётся фронтенду и не должен попадать в Git.

Перед подключением выполнен read-only запрос
`database/check_shared_supabase.sql`: проверены таблицы, RLS, сигнатуры и права
RPC, триггеры. Общая база уже содержит `request_events`, `create_hr_request`
и `review_hr_request`; конкурирующего триггера истории из `ver2` нет.
Повторно выполнять `0001`, `0002`, `seed.sql` или сбрасывать общую базу не нужно.
Дополнительные поля, добавленные командой, сохранены.

С согласия владельца задачи обновлены три старые демо-статьи и добавлены ещё
восемь. Все 15 локальных FAQ-карточек проверены на совпадение SHA-256 статьи и
дословной цитаты. Копия прежних статей сохранена локально в
`.venv/shared-knowledge-before-integration.json`. Это по-прежнему учебные
материалы, а не утверждённые кадровые правила JanaPost.

Созданы отдельные тестовые сотрудник и его руководитель с отметкой
`integration-smoke-test`. Их случайные пароли и идентификаторы находятся только
в `.venv/supabase-integration-accounts.json`; не публикуйте этот файл.
Существующие аккаунты команды не изменялись. Для проверки входите обычной
кнопкой «Войти в систему», а не через «Открыть демоверсию».

Проверка через настоящий Vite-прокси `http://127.0.0.1:5173/api/v1` подтвердила:

- вход обоих аккаунтов, обновление токенов и привязку HR-профилей;
- запрет анонимного доступа и доступа сотрудника к профилю руководителя;
- создание одной тестовой заявки на 10–12 ноября 2026 года, одобрение её
  руководителем и запрет самоодобрения;
- повторные отправку и одобрение без дублей: в Supabase одна заявка,
  два события истории и два уведомления (по одному каждому тестовому аккаунту);
- выгрузку ICS только после одобрения: начало 10 ноября, исключающая дата
  окончания 13 ноября, постоянный UID;
- ответ локальной Jana на переформулированный вопрос об отпуске, чтение статьи
  по защищённой ссылке и точное совпадение цитаты с содержимым базы;
- отказ без источников на вопросы о погоде и неизвестном размере зарплаты.

Дополнительно проверен браузер: обычный вход сотрудника, статус «PostTech API ·
Подключено», карточка одобренной заявки с историей, ответ Jana, открытие полного
источника и отказ на вопрос о погоде. Ошибок в консоли этой вкладки не обнаружено.

Заявка `00ccb0c2-2eb5-4797-ad3f-c038528486a2` (`REQ-528486A2`) и тестовые аккаунты
оставлены в общей базе с явными тестовыми пометками. Это не реальный отпуск.
Безопасный отчёт проверки находится в `.venv/supabase-live-check.json`;
проверочный календарь — `.venv/supabase-test-leave.ics`.

Для запуска используйте команды из начала документа: API на `127.0.0.1:8000`
и Vite на `127.0.0.1:5173`. Локальная модель уже установлена в `.models/mpnet`.
Платные API ИИ не вызываются; интернет нужен для Supabase Auth и базы знаний.
Импорт в Google Calendar остаётся ручным и в аккаунте Google не выполнялся.
