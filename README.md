# PostTech Digital HR MVP

FastAPI REST backend for the JanaMen Digital HR hackathon prototype. The MVP demonstrates one employee journey across profile, HR requests, Jana Academy, notifications, and AI Jana, with worker/manager/HR role enforcement.

AI integration: [контракт API, демо-база и локальный mock](docs/ai-jana-api.md).
The mock runs separately without credentials; the live AI routes retain Supabase authentication.
Real agent: [semantic evidence selection, verification and live evaluation](docs/ai-jana-agent.md).

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
| `PATCH /api/v1/requests/{id}/review` | Manager rejection is final; manager approval moves the request to `pending_hr`, then HR approves/rejects. Requests without a manager go directly to HR. |
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
2. Set `SUPABASE_URL`, the server-side `SUPABASE_KEY`, and the project's public `SUPABASE_ANON_KEY` in `.env`. The anon key is used only by the backend's Supabase Auth signup/login client; keep the server key private and never commit `.env`. Jana runs locally: install dependencies and run `python -m scripts.prepare_jana_local` once. No OpenAI key is used by the HTTP agent; missing local model files produce HTTP 503. The UI mock is a separate explicit process, never an automatic fallback.
3. Run [database/migrations/0001_digital_hr.sql](database/migrations/0001_digital_hr.sql), then [database/migrations/0002_request_hr_review.sql](database/migrations/0002_request_hr_review.sql) in the Supabase SQL editor.
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

---

# PostTech Digital HR MVP — русская версия

REST-бэкенд на FastAPI для хакатон-прототипа JanaMen Digital HR. MVP демонстрирует путь сотрудника через профиль, HR-заявки, Jana Academy, уведомления и AI Jana с проверкой ролей сотрудника, руководителя и HR.

## Архитектура

- `app/main.py` создаёт приложение FastAPI; `/api/v1` — версионированная граница API.
- `app/api/routes/` содержит HTTP-эндпоинты. `app/core/security.py` проверяет access-токены Supabase Auth и определяет HR-роль пользователя.
- `app/core/permissions.py` проверяет права владельца и руководителя команды перед чтением или изменением данных сотрудников.
- `app/db/supabase.py` создаёт серверный клиент Supabase; `app/services/` содержит логику уведомлений и Jana.
- `database/migrations/0001_digital_hr.sql` определяет схему MVP и включает RLS. `database/seed.sql` добавляет вымышленные демонстрационные данные и записи.
- Поток запроса: клиент -> проверка Bearer-токена -> проверка роли и прав доступа -> API-маршрут/сервис -> Supabase Postgres/Auth.

## Реализованный API

Для всех маршрутов, кроме `/` и `/api/v1/health/*`, требуется Bearer access-токен Supabase Auth.

| Эндпоинт | Назначение и права доступа |
| --- | --- |
| `POST /api/v1/auth/register` | Регистрация по email и паролю в Supabase Auth. Может потребоваться подтверждение email; HR должен связать Auth-пользователя с профилем сотрудника, прежде чем тот сможет пользоваться HR-эндпоинтами. |
| `POST /api/v1/auth/login` | Вход и получение `access_token` и `refresh_token`. |
| `POST /api/v1/auth/refresh` | Обмен refresh-токена на новую сессию. |
| `GET /api/v1/profile` | Только для чтения: HR-профиль текущего пользователя. |
| `GET /api/v1/employees/{employee_id}` | Собственный профиль; руководители могут просматривать прямых подчинённых, HR — все профили. |
| `GET /api/v1/team` | Для руководителей — прямые подчинённые; для HR — все профили. |
| `GET, POST /api/v1/requests` | Просмотр доступных заявок; создание заявок на отпуск или аванс. |
| `GET /api/v1/requests/{id}` | Просмотр заявки, только если профиль её сотрудника доступен текущему пользователю. |
| `PATCH /api/v1/requests/{id}/review` | Руководитель отклоняет заявку окончательно либо одобряет и передаёт её со статусом `pending_hr` в HR; HR принимает финальное решение. Заявки сотрудников без руководителя рассматривает HR напрямую. |
| `GET /api/v1/academy/courses` | Каталог активных курсов с состоянием назначений текущего пользователя. |
| `GET /api/v1/academy/my-courses` | Назначенные курсы и прогресс. |
| `GET /api/v1/academy/courses/{id}` | Материалы курса и тест; правильные ответы не возвращаются. |
| `POST /api/v1/academy/assignments` | HR или руководитель сотрудника назначает курс. |
| `PATCH /api/v1/academy/courses/{id}/progress` | Сохранение прогресса по курсу. |
| `POST /api/v1/academy/courses/{id}/complete` | Отправка ответов на тест; API рассчитывает и сохраняет результат. |
| `GET /api/v1/notifications` | Только уведомления текущего пользователя. |
| `POST /api/v1/notifications/{id}/read` | Отметить собственное уведомление как прочитанное. |
| `POST /api/v1/ai/ask` | Jana отвечает на основе найденных статей базы знаний, указывает источники либо отказывается отвечать и рекомендует обратиться в HR. |

Роли: `worker`, `manager` и `hr_admin`. Официальные данные профиля доступны только для чтения. В базе включена защита на уровне строк (RLS); прямой доступ из браузера с публичным ключом по умолчанию запрещён. Бэкенд использует серверный ключ Supabase и проверяет права на уровне API, поэтому этот ключ нельзя передавать клиенту.

## Настройка Supabase и демонстрационные данные

1. Создайте проект Supabase и скопируйте `.env.example` в `.env`.
2. Укажите в `.env` значения `SUPABASE_URL`, серверный `SUPABASE_KEY` и публичный `SUPABASE_ANON_KEY` проекта. Anon-ключ используется только серверным клиентом Supabase Auth для регистрации и входа; храните серверный ключ в секрете и никогда не коммитьте `.env`. Jana работает локально: установите зависимости и один раз выполните `python -m scripts.prepare_jana_local`. HTTP-агент не использует OpenAI-ключ; при отсутствии локальной модели возвращается HTTP 503. Mock для интерфейса запускается отдельно и не подменяет настоящий сервис при ошибке.
3. Выполните [database/migrations/0001_digital_hr.sql](database/migrations/0001_digital_hr.sql), затем [database/migrations/0002_request_hr_review.sql](database/migrations/0002_request_hr_review.sql) в SQL Editor проекта Supabase.
4. В Supabase Auth создайте вымышленных тестовых пользователей с адресами `hr@posttech.demo`, `manager@posttech.demo` и `employee@posttech.demo`. Задайте им демонстрационные пароли в Supabase; учётные данные не хранятся в этом репозитории.
5. Выполните [database/seed.sql](database/seed.sql). Скрипт создаёт вымышленные профили, два курса, статьи базы знаний, назначения курсов и примеры заявок/уведомлений. Реальные данные сотрудников не используются.
6. Зарегистрируйтесь через `POST /api/v1/auth/register`, при необходимости подтвердите email, затем войдите через `POST /api/v1/auth/login`. Передавайте полученный `access_token` в защищённые маршруты в заголовке `Authorization: Bearer <token>`. HR должен связать `user_id` из Auth с полем `auth_user_id` существующего профиля сотрудника. Публичная регистрация не позволяет назначать роль или изменять официальные данные сотрудника. Для обновления сессии отправьте её `refresh_token` в `POST /api/v1/auth/refresh`.

## Запуск

После настройки `.env` и выполнения демонстрационных SQL-скриптов запустите `docker compose up --build`. API доступен по адресу `http://localhost:8000`, Swagger UI — по адресу `http://localhost:8000/docs`.

Контейнер API может запуститься без `.env`, но эндпоинты, зависящие от Supabase, не будут работать без корректных учётных данных. `GET /api/v1/health/live` проверяет, что процесс работает. `/api/v1/health/ready` проверяет возможность инициализировать конфигурацию клиента Supabase, но не подтверждает успешное выполнение запроса к базе данных.

Для локальной разработки используйте Python 3.12, установите зависимости из `requirements-dev.txt` и запустите `uvicorn app.main:app --reload`.

## Область MVP и границы интеграций

- **Реализовано:** просмотр профилей с учётом ролей, процесс заявок на отпуск/аванс, рассмотрение заявок руководителем/HR, уведомления, назначенное обучение с серверной проверкой тестов и ответы/отказы Jana на основе источников.
- **Демонстрационные данные:** профили сотрудников — снимки данных с пометкой `mock-1c-zup`; курсы и статьи HR-политик вымышлены.
- **Пока не подключено:** действующие интеграции с 1С:ЗУП и Documentolog. Источник снимков профилей следует заменить адаптером 1С только для чтения, а адаптер Documentolog добавить за сервисной границей. Ни одна из интеграций не должна позволять сотрудникам изменять официальные данные.
- **Не входит в MVP:** реальные HR-политики и данные сотрудников, электронные подписи, хранение оригиналов документов, рекрутинг и решения по персоналу, принимаемые искусственным интеллектом.

## Тесты

Установите зависимости из `requirements-dev.txt` и запустите `pytest`. Демонстрационные пользователи и таблицы базы нужны только для интеграционных тестов; имеющиеся тесты health-эндпоинтов не требуют учётных данных Supabase.

## Локальная Jana и Google Calendar через файл

Рабочий AI теперь использует локальный поиск по смыслу и короткие утверждённые
FAQ-цитаты. Платного fallback нет. Экспорт календаря:
`GET /api/v1/requests/{uuid}/calendar.ics` с Bearer-токеном, только одобренный отпуск.

```powershell
python -m pip install -r requirements-dev.txt
python -m scripts.prepare_jana_local
python -m uvicorn examples.jana_local_demo:app --host 127.0.0.1 --port 8002
```

Локальная страница: http://127.0.0.1:8002. Реальная модель, вымышленные данные,
без Supabase. Для рабочего backend нужен Supabase и обновлённый demo seed.
Для Docker заранее подготовьте `.models/mpnet` на хосте; Compose монтирует его
только для чтения. Модель Apache 2.0, около 288 МБ; CPU, без Docker/GPU для локального запуска.

[Инструкция и результаты проверки](docs/ai-jana-agent.md) ·
[API и подключение frontend](docs/ai-jana-api.md)
