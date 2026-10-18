import { expect, test, type Page } from '@playwright/test';

type Role = 'worker' | 'manager' | 'hr_admin';
const ids = { own: '00000000-0000-4000-8000-000000000201', teammate: '00000000-0000-4000-8000-000000000205' };

async function enterDemo(page: Page, role: Role = 'worker') {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Демо-вход', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Демонстрация портала', exact: true })).toBeVisible();
  const labels = { worker: /^Сотрудник/, manager: /^Руководитель/, hr_admin: /^HR-администратор/ };
  await page.getByRole('radio', { name: labels[role] }).check();
  await page.getByRole('button', { name: 'Открыть демо', exact: true }).click();
  await expect(page.locator('.demo-banner')).toContainText('Демоверсия');
  await expect(page.locator('#main-content h1')).toBeVisible();
  await expect(page.locator('#main-content .loading-state')).toHaveCount(0);
}

async function navigate(page: Page, label: string) {
  if (label === 'Уведомления') { await page.getByRole('link', { name: /^Уведомления:/ }).click(); return; }
  if (['Профиль', 'Настройки', 'Календарь'].includes(label)) {
    await page.getByLabel('Меню профиля', { exact: true }).click();
    await page.locator('.account-popover').getByRole('link', { name: label === 'Профиль' ? 'Мой профиль' : label, exact: true }).click(); return;
  }
  const nav = page.getByRole('navigation', { name: (page.viewportSize()?.width ?? 1440) <= 900 ? 'Быстрая навигация' : 'Главная навигация' });
  if (label === 'Сотрудники') {
    const workspace = page.locator((page.viewportSize()?.width ?? 1440) <= 900 ? '.workspace-switch-mobile' : '.workspace-switch-desktop');
    await workspace.getByRole('button', { name: 'Команда', exact: true }).click();
    await nav.getByRole('link', { name: 'Команда', exact: true }).click(); return;
  }
  if (label === 'AI Jana') {
    if ((page.viewportSize()?.width ?? 1440) <= 900) await nav.getByRole('link', { name: 'Помощь', exact: true }).click();
    else await page.locator('.sidebar-bottom').getByRole('link', { name: 'Помощь', exact: true }).click();
    await page.locator('.workspace-links').getByRole('link', { name: /^Спросить Jana/ }).click(); return;
  }
  await nav.getByRole('link', { name: label, exact: true }).click();
}

async function confirmRequest(page: Page) {
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click();
  const submit = page.getByRole('button', { name: 'Отправить заявку', exact: true });
  await expect(submit).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Проверьте заявку' })).toBeVisible();
  await submit.click();
}

test('demo entry, responsive navigation and readonly profile', async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await enterDemo(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
  await page.screenshot({ path: `test-results/dashboard-${testInfo.project.name}.png`, fullPage: true, animations: 'disabled' });
  await navigate(page, 'Профиль');
  await expect(page.getByRole('heading', { name: 'Мой профиль', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Личные данные' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Данные о работе' })).toBeVisible();
  if ((page.viewportSize()?.width ?? 1440) <= 900) {
    await expect(page.locator('#profile-personal')).toBeHidden();
    await expect(page.locator('#profile-work')).toBeHidden();
    await page.getByRole('button', { name: 'Личные данные', exact: true }).click();
    await expect(page.locator('#profile-personal')).toBeVisible();
    await expect(page.locator('#profile-personal')).toContainText('Алия Серикова');
    await page.getByRole('button', { name: 'Данные о работе', exact: true }).click();
    await expect(page.locator('#profile-personal')).toBeHidden();
    await expect(page.locator('#profile-work')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Профиль', exact: true }).getByRole('link', { name: 'История', exact: true })).toHaveAttribute('href', '/activity');
  } else {
    await expect(page.locator('#profile-personal')).toBeVisible();
    await expect(page.locator('#profile-work')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Оформить отпуск', exact: true })).toHaveAttribute('href', '/calendar?select=1');
  }
  await expect(page.locator('#main-content input')).toHaveCount(0);
  await expect(page.locator('#main-content')).toContainText('Алия Серикова');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  expect(overflow).toBe(false);
  expect(pageErrors).toEqual([]);
});

test('advance requires confirmation, creates one request and shows its history', async ({ page }, testInfo) => {
  await enterDemo(page);
  await navigate(page, 'Заявки');
  await expect(page.locator('.req-list-card tbody tr')).not.toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
  await page.screenshot({ path: `test-results/requests-${testInfo.project.name}.png`, fullPage: true, animations: 'disabled' });
  await page.getByRole('link', { name: 'Создать заявку' }).click();
  await page.getByRole('button', { name: 'Аванс', exact: true }).click();
  await page.getByLabel('Сумма, ₸').fill('12345.67');
  await page.getByRole('textbox', { name: /^Комментарий/ }).fill('Проверка оформления аванса');
  await confirmRequest(page);
  await expect(page.getByRole('heading', { name: 'Заявка отправлена!', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Открыть заявку', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Заявка на аванс', exact: true })).toBeVisible();
  await expect(page.locator('.req-detail-summary')).toContainText(/12\s345,67/);
  await expect(page.locator('.req-history')).toContainText('Заявка подана сотрудником');
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toHaveCount(0);
  await navigate(page, 'Заявки');
  await page.getByRole('textbox', { name: 'Поиск заявок', exact: true }).fill('Проверка оформления аванса');
  await expect(page.locator('.req-list-card tbody tr')).toHaveCount(1);
});

test('calendar navigation and range selection carry dates into request review', async ({ page }, testInfo) => {
  await enterDemo(page);
  await navigate(page, 'Календарь');
  await expect(page.locator('.cal-month-grid')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
  await page.screenshot({ path: `test-results/calendar-${testInfo.project.name}.png`, fullPage: true, animations: 'disabled' });
  const month = page.locator('.cal-month-controls strong');
  const initialMonth = (await month.textContent())!.trim();
  await page.getByRole('button', { name: 'Следующий месяц', exact: true }).click();
  await expect(month).not.toHaveText(initialMonth);
  await page.getByRole('button', { name: 'Предыдущий месяц', exact: true }).click();
  await expect(month).toHaveText(initialMonth);
  await page.getByRole('button', { name: 'Оформить отпуск', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Продолжить', exact: true })).toBeDisabled();
  await expect(page.getByLabel('Дата начала', { exact: true })).toBeHidden();
  await page.getByText('Ввести даты вручную', { exact: true }).click();
  await page.getByLabel('Дата начала', { exact: true }).fill('2030-11-03');
  await page.getByLabel('Дата окончания', { exact: true }).fill('2030-11-06');
  await expect(page.locator('.cal-selected-period')).toContainText('4 дня');
  await page.getByRole('button', { name: 'Продолжить', exact: true }).click();
  await expect(page).toHaveURL(/\/requests\/new\?/);
  await expect(page.getByRole('heading', { name: 'Проверьте заявку', exact: true })).toBeVisible();
  await expect(page.locator('.req-review-summary')).toContainText(/3 нояб.*2030.*6 нояб.*2030/);
  await expect(page.locator('.req-review-summary')).toContainText('4 календарных дня');
  const submit = page.getByRole('button', { name: 'Отправить заявку', exact: true });
  await expect(submit).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Проверьте заявку' })).toBeVisible();
  await submit.click();
  await expect(page.getByRole('heading', { name: 'Заявка отправлена!', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Открыть заявку', exact: true }).click();
  await expect(page.locator('.req-detail-summary')).toContainText('4 календарных дня');
  await expect(page.locator('.req-detail-summary')).toContainText(/3 нояб.*2030.*6 нояб.*2030/);
  await expect(page.locator('.req-history')).toContainText('Заявка подана сотрудником');
});

test('assigned course records server-scored quiz completion', async ({ page }) => {
  await enterDemo(page);
  await navigate(page, 'Обучение');
  const course = page.locator('article').filter({ has: page.getByRole('heading', { name: 'Безопасность персональных данных', exact: true }) });
  await course.getByRole('button', { name: 'Продолжить', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Бережно к данным');
  await dialog.getByRole('button', { name: 'Перейти к тесту', exact: true }).click();
  await dialog.getByRole('button', { name: 'Завершить тест', exact: true }).click();
  await expect(dialog).not.toContainText('Обучение завершено');
  await dialog.getByRole('radio', { name: 'Любого сотрудника компании', exact: true }).check();
  await dialog.getByRole('radio', { name: 'Попросить придумать ответ', exact: true }).check();
  await dialog.getByRole('button', { name: 'Завершить тест', exact: true }).click();
  await expect(dialog.getByRole('heading', { name: 'Попробуйте ещё раз' })).toBeVisible();
  await expect(dialog.locator('.support-result-score')).toHaveText('0%');
  await expect(dialog.locator('.academy-attempts li')).toHaveCount(1);
  await expect(dialog.locator('.academy-attempts')).toContainText('Нужен повтор');
  await dialog.getByRole('button', { name: 'Повторить тест', exact: true }).click();
  await dialog.getByRole('radio', { name: 'Своей команды', exact: true }).check();
  await dialog.getByRole('radio', { name: 'Обратиться в HR', exact: true }).check();
  await dialog.getByRole('button', { name: 'Завершить тест', exact: true }).click();
  await expect(dialog.getByRole('heading', { name: 'Обучение завершено' })).toBeVisible();
  await expect(dialog.locator('.support-result-score')).toHaveText('100%');
  await expect(dialog.locator('.academy-attempts li')).toHaveCount(2);
  await dialog.getByRole('button', { name: 'Вернуться к курсам' }).click();
  await expect(course).toContainText('Завершён');
  await expect(course.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
});

test('Jana cites supported answers and explicitly handles unknown questions', async ({ page }) => {
  await enterDemo(page);
  const currentUrl = page.url();
  await page.getByRole('button', { name: 'Открыть AI Jana' }).click();
  const chat = page.getByRole('dialog', { name: 'Чат с AI Jana' });
  await expect(chat).toBeVisible();
  expect(page.url()).toBe(currentUrl);
  await chat.getByRole('button', { name: 'Как оформить отпуск?', exact: true }).click();
  const conversation = chat.getByRole('log', { name: 'Сообщения диалога' });
  await expect(conversation).toContainText('Демо: порядок оформления отпуска');
  await chat.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Какова температура поверхности Венеры?');
  await chat.getByRole('button', { name: 'Отправить вопрос' }).click();
  await expect(conversation).toContainText('нет подтверждённой информации');
  await expect(conversation.getByRole('button', { name: 'Передать вопрос в HR' })).toBeVisible();
  await chat.getByRole('button', { name: 'Новый диалог' }).click();
  await expect(chat.getByRole('heading', { name: 'Чем помочь?' })).toBeVisible();
  await chat.getByRole('button', { name: 'Закрыть AI Jana' }).click();
  await expect(chat).toBeHidden();
});

test('notification read state updates and density preference survives reload', async ({ page }) => {
  await enterDemo(page);
  await navigate(page, 'Уведомления');
  await page.getByRole('button', { name: 'Непрочитанные', exact: true }).click();
  await expect(page.locator('.support-notification')).toHaveCount(2);
  await page.getByRole('button', { name: /^Отметить прочитанным:/ }).first().click();
  await expect(page.locator('.support-notification')).toHaveCount(1);
  await page.getByRole('button', { name: /^Отметить прочитанным:/ }).click();
  await expect(page.getByRole('heading', { name: 'Все уведомления прочитаны' })).toBeVisible();
  await navigate(page, 'Настройки');
  await page.getByRole('switch', { name: 'Компактный интерфейс' }).check();
  await expect(page.locator('body')).toHaveAttribute('data-density', 'compact');
  await page.reload();
  await expect(page.getByRole('switch', { name: 'Компактный интерфейс' })).toBeChecked();
  await expect(page.locator('body')).toHaveAttribute('data-density', 'compact');
  await page.locator('#main-content').getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page.getByRole('heading', { name: /^Вход(?: в PostTech)?$/ })).toBeVisible();
});

test('manager cannot review own request and can review a teammate request', async ({ page }) => {
  await enterDemo(page, 'manager');
  await page.goto(`/requests/${ids.own}`);
  await expect(page.getByRole('heading', { name: 'Заявка на отпуск', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Согласовать заявку' })).toHaveCount(0);
  await page.goto(`/requests/${ids.teammate}`);
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toBeVisible();
  await page.getByLabel('Комментарий к решению').fill('Даты согласованы, передача задач подтверждена.');
  await page.getByRole('button', { name: 'Согласовать заявку' }).click();
  await expect(page.locator('.req-history')).not.toContainText('Заявка согласована');
  await page.getByRole('button', { name: 'Подтвердить решение' }).click();
  await expect(page.locator('.req-history')).toContainText('Заявка согласована');
  await expect(page.locator('.req-reviewer-comment')).toContainText('Даты согласованы');
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toHaveCount(0);
});

test('manager assigns an available course and duplicate assignment stays an error', async ({ page }) => {
  await enterDemo(page, 'manager');
  await navigate(page, 'Сотрудники');
  const openEmployee = () => page.getByRole('button', { name: 'Профиль: Алия Серикова', exact: true }).click();
  await openEmployee();
  await expect(page.getByRole('dialog')).toContainText('данные обновляет HR');
  await expect(page.getByRole('dialog').locator('input, textarea, select')).toHaveCount(0);
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить курс', exact: true }).click();
  await page.getByRole('dialog').getByRole('radio', { name: /Эффективная работа в команде/ }).check();
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить курс', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.toast')).toContainText('Курс назначен');
  await openEmployee();
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить курс', exact: true }).click();
  await page.getByRole('dialog').getByRole('radio', { name: /Эффективная работа в команде/ }).check();
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить курс', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('уже назначен');
});

test('live login uses bearer auth and retries an uncertain request after reload with the same idempotency key', async ({ page }) => {
  const employeeId = '40000000-0000-4000-8000-000000000001';
  const requestId = '40000000-0000-4000-8000-000000000002';
  const writes: { body: Record<string, unknown>; authorization?: string; idempotency?: string }[] = [];
  const protectedHeaders: (string | undefined)[] = [];
  const profile = { id: employeeId, employee_code: 'TEST-01', full_name: 'Тестовый Сотрудник', email: 'employee@example.test', company: 'PostTech', job_title: 'Оператор', department: 'Хаб', manager_id: null, hired_at: '2023-01-10', vacation_days_remaining: 24, role: 'worker', external_source: 'test', created_at: '2026-01-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z' };
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/auth/login') return respond({ user_id: 'test-auth-user', email: profile.email, access_token: 'test-access-token', refresh_token: 'test-refresh-token', token_type: 'bearer', expires_in: 3600 });
    protectedHeaders.push(request.headers().authorization);
    if (path === '/workspace/leave-balance') return respond({employee_id:profile.id,official_days:24,pending_days:0,approved_unreconciled_days:0,available_days:24,request_days:0,holds:[]});
    if (path === '/profile') return respond(profile);
    if (path === '/requests/routing') return respond({ can_submit: true, route: 'manager', approvers: [{ id: '40000000-0000-4000-8000-000000000003', full_name: 'Тестовый Руководитель', role: 'manager' }], message: null, today: '2026-10-16', policy: 'Заявку рассматривает руководитель.' });
    if (path === '/requests' && request.method() === 'POST') {
      const body = request.postDataJSON() as Record<string, unknown>;
      writes.push({ body, authorization: request.headers().authorization, idempotency: request.headers()['idempotency-key'] });
      // Simulate a request accepted by the service whose acknowledgement never reaches the browser.
      if (writes.length === 1) return route.abort('failed');
      return respond({ id: requestId, employee_id: employeeId, ...body, status: 'pending', start_date: null, end_date: null, reviewed_by: null, reviewer_comment: null, reviewed_at: null, created_at: '2026-10-16T10:00:00Z', updated_at: '2026-10-16T10:00:00Z' }, 201);
    }
    return respond([]);
  });
  await page.goto('/login');
  await page.getByLabel('Рабочая почта', { exact: true }).fill(profile.email);
  await page.getByRole('button', { name: 'Забыли пароль?', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Восстановить пароль', exact: true })).toBeVisible();
  await expect(page.getByLabel('Рабочая почта', { exact: true })).toHaveValue(profile.email);
  await page.getByRole('button', { name: 'У меня уже есть код', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Новый пароль', exact: true })).toBeVisible();
  await page.getByRole('textbox', { name: 'Код подтверждения', exact: true }).fill('12345678');
  await expect(page.locator('.onboarding-otp-cell')).toHaveCount(8);
  await page.locator('input[autocomplete="new-password"]').fill('NotSubmittedPassword123!');
  await page.getByRole('button', { name: 'Назад', exact: true }).click();
  await expect(page.getByLabel('Рабочая почта', { exact: true })).toHaveValue(profile.email);
  await page.getByRole('button', { name: 'Назад', exact: true }).click();
  await expect(page.getByRole('heading', { name: /^Вход(?: в PostTech)?$/ })).toBeVisible();
  await expect(page.locator('input[autocomplete="current-password"]')).toHaveValue('');
  await page.locator('input[autocomplete="current-password"]').fill('TestPassword123!');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.locator('.demo-banner')).toHaveCount(0);
  await navigate(page, 'Заявки');
  await page.getByRole('link', { name: 'Создать заявку' }).click();
  await page.getByRole('button', { name: 'Аванс', exact: true }).click();
  await page.getByLabel('Сумма, ₸').fill('25000.50');
  await page.getByRole('textbox', { name: /^Комментарий/ }).fill('Запрос из браузера');
  await page.getByRole('button', { name: 'Черновик', exact: true }).click();
  await confirmRequest(page);
  await expect(page.getByRole('alert')).toContainText('Не удалось связаться с сервером');
  await expect(page.getByRole('heading', { name: 'Заявка отправлена!', exact: true })).toHaveCount(0);
  expect(await page.evaluate(id => sessionStorage.getItem(`posttech-request-pending:live:${id}`), employeeId)).not.toBeNull();
  await page.reload();
  await page.getByRole('button', { name: 'Восстановить', exact: true }).click();
  await expect(page.getByLabel('Сумма, ₸')).toHaveValue('25000.50');
  await expect(page.getByRole('textbox', { name: /^Комментарий/ })).toHaveValue('Запрос из браузера');
  await confirmRequest(page);
  await expect(page.getByRole('heading', { name: 'Заявка отправлена!', exact: true })).toBeVisible();
  expect(writes).toHaveLength(2);
  expect(writes[0].body).toEqual({ request_type: 'advance', amount: 25000.5, comment: 'Запрос из браузера' });
  expect(writes[1].body).toEqual(writes[0].body);
  expect(writes[0].authorization).toBe('Bearer test-access-token');
  expect(writes[0].idempotency).toMatch(/^[\da-f]{8}-[\da-f-]{27}$/i);
  expect(writes[1].idempotency).toBe(writes[0].idempotency);
  expect(protectedHeaders.every(header => header === 'Bearer test-access-token')).toBe(true);
  expect(await page.evaluate(id => sessionStorage.getItem(`posttech-request-pending:live:${id}`), employeeId)).toBeNull();
  expect(await page.evaluate(id => sessionStorage.getItem(`posttech-request-draft:live:${id}`), employeeId)).toBeNull();
});

test('unread pagination waits for pending writes and keeps older unread messages reachable', async ({ page }) => {
  const employeeId = '50000000-0000-4000-8000-000000000001';
  const notes = Array.from({ length: 26 }, (_, index) => ({ id: `notification-${index + 1}`, employee_id: employeeId, request_id: null, notification_type: 'test', title: `Событие ${index + 1}`, body: 'Проверка последовательного чтения', read_at: null as string | null, created_at: '2026-10-16T10:00:00Z' }));
  const offsets: number[] = [];
  let releaseRead!: () => void;
  let reportReadStarted!: () => void;
  const readGate = new Promise<void>(resolve => { releaseRead = resolve; });
  const readStarted = new Promise<void>(resolve => { reportReadStarted = resolve; });
  await page.addInitScript(() => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({ user_id: 'test-auth-user', email: 'test@example.test', access_token: 'test-access-token', refresh_token: 'test-refresh-token', token_type: 'bearer', expires_in: 3600, expires_at: Date.now() + 3_600_000 })));
  await page.route('**/api/v1/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1', '');
    const respond = (body: unknown) => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/profile') return respond({ id: employeeId, employee_code: 'TEST-01', full_name: 'Тестовый Сотрудник', email: 'test@example.test', company: 'PostTech', job_title: 'Оператор', department: 'Хаб', manager_id: null, hired_at: '2023-01-10', vacation_days_remaining: 24, role: 'worker', external_source: 'test', created_at: '2026-01-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z' });
    if (path.endsWith('/read')) {
      const id = path.split('/')[2];
      if (id === 'notification-1') { reportReadStarted(); await readGate; }
      const notification = notes.find(note => note.id === id)!;
      notification.read_at = '2026-10-16T11:00:00Z';
      return respond(notification);
    }
    if (path === '/notifications') {
      const limit = Number(url.searchParams.get('limit') || 100);
      const offset = Number(url.searchParams.get('offset') || 0);
      if (limit === 25) offsets.push(offset);
      const filtered = url.searchParams.get('unread_only') === 'true' ? notes.filter(note => !note.read_at) : notes;
      return respond(filtered.slice(offset, offset + limit));
    }
    return respond([]);
  });
  await page.goto('/notifications');
  await page.getByRole('button', { name: 'Непрочитанные', exact: true }).click();
  await expect(page.locator('.support-notification')).toHaveCount(25);
  await page.getByRole('button', { name: /^Отметить прочитанным:/ }).first().click();
  await readStarted;
  await expect(page.getByRole('button', { name: 'Показать ещё', exact: true })).toBeDisabled();
  releaseRead();
  await expect(page.getByRole('heading', { name: 'Событие 1', exact: true })).toHaveCount(0);
  for (let index = 2; index <= 26; index += 1) {
    const action = page.getByRole('button', { name: `Отметить прочитанным: Событие ${index}`, exact: true });
    if (!(await action.isVisible()) && await page.getByRole('button', { name: 'Показать ещё', exact: true }).isVisible()) {
      await page.getByRole('button', { name: 'Показать ещё', exact: true }).click();
    }
    await action.click();
    await expect(action).toHaveCount(0);
  }
  await expect(page.getByRole('heading', { name: 'Все уведомления прочитаны' })).toBeVisible();
  expect(notes.every(note => note.read_at)).toBe(true);
  expect(offsets).toContain(0);
});
