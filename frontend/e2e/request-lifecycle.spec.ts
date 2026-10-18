import { expect, test, type Page } from '@playwright/test';
import type { EmployeeProfile, HrRequest, RequestEvent, RequestRouting } from '../src/lib/types';

const ownId = '70000000-0000-4000-8000-000000000001';
const employeeId = '70000000-0000-4000-8000-000000000002';
const hrId = '70000000-0000-4000-8000-000000000003';
const requestId = '70000000-0000-4000-8000-000000000101';
const otherRequestId = '70000000-0000-4000-8000-000000000102';
const stamp = '2026-10-16T10:00:00Z';
const approver = { id: ownId, full_name: 'Тестовый руководитель', role: 'manager' as const };
const hr = { id: hrId, full_name: 'Тестовый HR', role: 'hr_admin' as const };

function request(overrides: Partial<HrRequest> = {}): HrRequest {
  return { id: requestId, employee_id: ownId, request_type: 'leave', status: 'pending', start_date: '2030-11-03', end_date: '2030-11-06', amount: null, comment: 'Плановый отпуск', reviewer_comment: null, reviewed_by: null, reviewed_at: null, created_at: stamp, updated_at: stamp, approval_route: 'hr', approvers: [hr], cancelled_at: null, ...overrides };
}

async function mockPortal(page: Page, options: { role?: EmployeeProfile['role']; records?: HrRequest[]; routing?: RequestRouting; teamUnavailable?: boolean } = {}) {
  const records = options.records || [];
  const writes: { path: string; body: Record<string, unknown> | null }[] = [];
  const scopes: string[] = [];
  const history: Record<string, RequestEvent[]> = Object.fromEntries(records.map(item => [item.id, [{ id: `${item.id}-created`, request_id: item.id, actor_id: item.employee_id, event_type: 'created', from_status: null, to_status: 'pending', comment: item.comment, created_at: stamp }]]));
  const profile = { id: ownId, employee_code: 'TEST-01', full_name: 'Тестовый руководитель', email: 'request@example.test', company: 'PostTech', job_title: 'Руководитель', department: 'Хаб', manager_id: null, hired_at: '2023-01-10', vacation_days_remaining: 24, role: options.role || 'manager', external_source: 'test', created_at: stamp, updated_at: stamp };
  await page.addInitScript(() => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({ user_id: 'test-auth-user', email: 'request@example.test', access_token: 'test-access-token', refresh_token: 'test-refresh-token', token_type: 'bearer', expires_in: 3600, expires_at: Date.now() + 3_600_000 })));
  await page.route('**/api/v1/**', async route => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace('/api/v1', '');
    const respond = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
    if (path === '/workspace/leave-balance') return respond({employee_id:ownId,official_days:24,pending_days:4,approved_unreconciled_days:0,available_days:20,request_days:4,holds:[]});
    if (path === '/profile') return respond(profile);
    if (path === '/requests/routing') return respond(options.routing || { can_submit: true, route: 'hr', approvers: [hr], message: null, today: '2026-10-16', policy: 'Calendar days; official balance read only' });
    if (path === '/team') return options.teamUnavailable ? respond({ detail: 'Forbidden' }, 403) : respond([{ ...profile, id: employeeId, role: 'worker', full_name: 'Сотрудник команды', manager_id: ownId }]);
    if (path === '/requests' && req.method() === 'GET') {
      const scope = url.searchParams.get('scope') || 'all';
      scopes.push(scope);
      const filtered = records.filter(item => scope === 'mine' ? item.employee_id === ownId : scope === 'review' ? item.employee_id !== ownId : true);
      return respond(filtered);
    }
    const found = records.find(item => path === `/requests/${item.id}` || path.startsWith(`/requests/${item.id}/`));
    if (found && path.endsWith('/history')) return respond(history[found.id]);
    if (found && path.endsWith('/cancel') && req.method() === 'POST') {
      writes.push({ path, body: null });
      found.status = 'cancelled'; found.cancelled_at = stamp;
      history[found.id].push({ id: `${found.id}-cancelled`, request_id: found.id, actor_id: ownId, event_type: 'cancelled', from_status: 'pending', to_status: 'cancelled', comment: 'Отозвана автором', created_at: stamp });
      return respond(found);
    }
    if (found && path.endsWith('/review') && req.method() === 'PATCH') {
      const body = req.postDataJSON();
      writes.push({ path, body });
      found.status = body.status; found.reviewer_comment = body.reviewer_comment; found.reviewed_by = ownId; found.reviewed_at = stamp;
      history[found.id].push({ id: `${found.id}-reviewed`, request_id: found.id, actor_id: ownId, event_type: body.status, from_status: 'pending', to_status: body.status, comment: body.reviewer_comment, created_at: stamp });
      return respond(found);
    }
    if (found) return respond(found);
    return respond([]);
  });
  return { records, writes, scopes };
}

test('open reviewer inbox receives new requests without navigation and preserves search', async ({ page }) => {
  const { records, scopes } = await mockPortal(page);
  await page.goto('/requests?scope=review');
  await expect.poll(() => scopes.length).toBeGreaterThan(0);
  const search = page.getByRole('textbox', { name: 'Поиск заявок', exact: true });
  await search.fill('Плановый');
  records.push(request({ employee_id: employeeId, approval_route: 'manager', approvers: [approver] }));
  await expect(page.locator('.req-list-card tbody tr')).toHaveCount(1, { timeout: 8000 });
  await expect(search).toHaveValue('Плановый');
  records[0].status = 'approved';
  await expect(page.locator('.req-list-card tbody tr')).toHaveCount(0, { timeout: 8000 });
  expect(scopes.every(scope => scope === 'review')).toBe(true);
});

test('home refreshes external requests and available leave without navigation', async ({ page }) => {
  const { records } = await mockPortal(page, { role: 'worker' });
  let available = 24;
  await page.route('**/api/v1/workspace/leave-balance', route => route.fulfill({ json: { employee_id: ownId, official_days: 24, available_days: available, pending_days: 24 - available, approved_unreconciled_days: 0, request_days: 0, holds: [] } }));
  await page.goto('/');
  await expect(page.locator('.desk-leave-copy')).toContainText('24 дн. доступно');
  records.push(request()); available = 20;
  await expect(page.locator('.desk-request')).toHaveCount(1);
  await expect(page.locator('.desk-leave-copy')).toContainText('20 дн. доступно');
  records[0].status = 'approved';
  await expect(page.locator('.desk-request')).toContainText('Согласовано');
});

test('notifications refresh externally read items while preserving loaded pages', async ({ page }) => {
  await mockPortal(page);
  const notes = Array.from({ length: 30 }, (_, i) => ({ id: `note-${i}`, employee_id: ownId, request_id: null, notification_type: 'request_approved', title: `Событие ${i}`, body: 'Изменение заявки', read_at: null as string | null, created_at: stamp }));
  await page.route('**/api/v1/notifications?*', route => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get('offset') || 0);
    const limit = Number(url.searchParams.get('limit') || 25);
    const filtered = url.searchParams.get('unread_only') === 'true' ? notes.filter(n => !n.read_at) : notes;
    return route.fulfill({ json: filtered.slice(offset, offset + limit) });
  });
  await page.goto('/notifications');
  await expect(page.locator('.support-notification')).toHaveCount(25);
  await page.getByRole('button', { name: 'Показать ещё' }).click();
  await expect(page.locator('.support-notification')).toHaveCount(30);
  notes[0].read_at = stamp;
  notes.unshift({ ...notes[1], id: 'new', title: 'Новое событие' });
  await expect(page.locator('.support-notification')).toHaveCount(31);
  await expect(page.getByRole('heading', { name: 'Событие 0', exact: true }).locator('xpath=ancestor::article')).not.toHaveClass(/unread/);
  await expect(page.getByRole('heading', { name: 'Событие 29', exact: true })).toBeVisible();
});

test('open request receives external decision without navigation', async ({ page }) => {
  const { records } = await mockPortal(page, { records: [request()] });
  await page.goto(`/requests/${requestId}`);
  await expect(page.getByRole('region', { name: 'Состояние заявки' })).toContainText('Согласует:');
  records[0].status = 'approved';
  records[0].reviewed_by = hrId;
  records[0].reviewed_at = stamp;
  await expect(page.getByRole('region', { name: 'Состояние заявки' })).toContainText('Заявка согласована', { timeout: 8000 });
});

test('owner sees saved HR route and cancels only after confirmation', async ({ page }) => {
  const { writes } = await mockPortal(page, { records: [request()] });
  await page.goto(`/requests/${requestId}`);
  await expect(page.locator('.req-routing-card')).toContainText('Тестовый HR');
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Состояние заявки' })).toContainText('Согласует: Тестовый HR');
  await expect(page.getByRole('link', { name: 'Перейти к решению' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Отозвать заявку', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog).toContainText('Возобновить эту заявку нельзя');
  expect(writes).toHaveLength(0);
  await dialog.getByRole('button', { name: 'Оставить заявку' }).click();
  await expect(dialog).toHaveCount(0);
  await page.getByRole('button', { name: 'Отозвать заявку', exact: true }).click();
  await dialog.getByRole('button', { name: 'Подтвердить отзыв' }).click();
  await expect(page.locator('.req-history')).toContainText('Заявка отозвана автором');
  await expect(page.getByRole('button', { name: 'Отозвать заявку', exact: true })).toHaveCount(0);
  expect(writes).toEqual([{ path: `/requests/${requestId}/cancel`, body: null }]);
});

test('no available approver blocks submission and leaves draft available', async ({ page }) => {
  const { writes } = await mockPortal(page, { role: 'hr_admin', routing: { can_submit: false, route: 'unassigned', approvers: [], message: 'No eligible approver', today: '2026-10-16', policy: 'Calendar days' } });
  await page.goto('/requests/new?type=advance');
  await expect(page.locator('.req-route-unavailable')).toContainText('Не назначен согласующий');
  await page.getByLabel('Сумма, ₸').fill('5000');
  await expect(page.getByRole('button', { name: 'Продолжить' })).toBeDisabled();
  await page.getByRole('button', { name: 'Черновик' }).click();
  await expect(page.locator('.toast')).toContainText('Черновик сохранён');
  expect(writes).toHaveLength(0);
});

test('review inbox excludes own request and rejection requires a reason even if team profiles fail', async ({ page }) => {
  const { writes, scopes } = await mockPortal(page, { teamUnavailable: true, records: [request(), request({ id: otherRequestId, employee_id: employeeId, approval_route: 'manager', approvers: [approver], comment: 'Заявка другого сотрудника' })] });
  await page.goto('/requests?scope=review');
  await expect(page.getByRole('heading', { name: 'На согласование', exact: true })).toBeVisible();
  await expect(page.locator('.req-table tbody tr')).toHaveCount(1);
  expect(scopes).toContain('review');
  await page.locator('.req-table-title').click();
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toBeVisible();
  await page.getByRole('link', { name: 'Перейти к решению' }).click();
  await expect(page.locator('#request-decision')).toBeFocused();
  await expect(page.getByRole('button', { name: 'Отозвать заявку', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Отклонить', exact: true })).toBeDisabled();
  await page.getByLabel('Комментарий к решению').fill('  Нужен другой период  ');
  await page.getByRole('button', { name: 'Отклонить', exact: true }).click();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: 'Подтвердить решение' }).click();
  await expect(page.locator('.req-history')).toContainText('Заявка отклонена');
  await expect(page.locator('.req-reviewer-comment')).toContainText('Нужен другой период');
  expect(writes).toEqual([{ path: `/requests/${otherRequestId}/review`, body: { status: 'rejected', reviewer_comment: 'Нужен другой период' } }]);
});

test('calendar refuses past and overlapping leave ranges, then passes a free range to form', async ({ page }) => {
  await mockPortal(page, { records: [request()] });
  await page.goto('/calendar?select=1');
  await page.getByText('Ввести даты вручную', { exact: true }).click();
  const start = page.getByLabel('Дата начала', { exact: true });
  const end = page.getByLabel('Дата окончания', { exact: true });
  const proceed = page.getByRole('button', { name: 'Продолжить' });
  await expect(start).toHaveAttribute('min', /20\d\d-\d\d-\d\d/);
  await start.fill('2020-01-01'); await end.fill('2020-01-02');
  await expect(page.getByRole('alert')).toContainText('сегодня или позже');
  await expect(proceed).toBeDisabled();
  await start.fill('2030-11-06'); await end.fill('2030-11-08');
  await expect(page.getByRole('alert')).toContainText('пересекается');
  await expect(page.locator('.req-conflict')).toContainText('Ждёт решения');
  await expect(page.locator('.req-conflict')).toContainText('Согласует: Тестовый HR');
  await expect(page.locator('.req-conflict')).toContainText('3 нояб. 2030');
  await expect(page.locator('.req-conflict').getByRole('link', { name: 'Открыть заявку' })).toHaveAttribute('href', `/requests/${requestId}`);
  await expect(proceed).toBeDisabled();
  await page.getByRole('button', { name: 'Выбрать другие даты' }).click();
  await expect(start).toHaveValue('');
  await expect(end).toHaveValue('');
  await expect(page.locator('.req-conflict')).toHaveCount(0);
  await start.fill('2030-11-07'); await end.fill('2030-11-08');
  await expect(proceed).toBeEnabled();
  await proceed.click();
  await expect(page).toHaveURL(/start=2030-11-07&end=2030-11-08/);
  await expect(page.getByRole('heading', { name: 'Проверьте заявку' })).toBeVisible();
  await expect(page.locator('.req-review-hero')).toContainText('7 нояб. 2030');
  await expect(page.locator('.req-review-approver')).toContainText('Тестовый HR');
  await expect(page.getByRole('button', { name: 'Отправить заявку', exact: true })).toBeEnabled();
  await expect(page.getByRole('checkbox', { name: 'Данные верны, можно отправлять' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Изменить', exact: true }).click();
  await expect(page.getByLabel('Дата начала', { exact: true })).toHaveValue('2030-11-07');
});

test('all conflicting requests remain discoverable on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 780 });
  await mockPortal(page, { role: 'worker', records: [request(), request({ id: otherRequestId, status: 'approved', start_date: '2030-11-10', end_date: '2030-11-12' })] });
  await page.goto('/calendar?select=1&start=2030-11-05&end=2030-11-11');
  await expect(page.locator('.req-conflict-list>li')).toHaveCount(2);
  await expect(page.locator('.req-conflict')).toContainText('Согласовано');
  await expect(page.getByRole('button', { name: 'Продолжить' })).toBeDisabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('.req-conflict-list>li').last().getByRole('link', { name: 'Открыть заявку' }).click();
  await expect(page.getByRole('region', { name: 'Состояние заявки' })).toContainText('Решение сохранено');
  await expect(page.getByRole('button', { name: 'Согласовать заявку' })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('manager mobile navigation opens the review inbox and personal leave stays separate', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockPortal(page, { records: [request(), request({ id: otherRequestId, employee_id: employeeId, approvers: [approver], can_review: true })] });
  await page.goto('/requests');
  await page.locator('.workspace-switch-mobile').getByRole('button', { name: 'Команда', exact: true }).click();
  await expect(page).toHaveURL(/scope=review/);
  await expect(page.locator('.req-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.req-table')).toContainText('Ждёт вашего решения');
  await page.locator('.req-open-link').click();
  await expect(page.locator('.req-workflow-summary')).toContainText('Нужно ваше решение');
  await page.locator('.req-back').click();
  await expect(page).toHaveURL(/scope=review/);
  await page.locator('.workspace-switch-mobile').getByRole('button', { name: 'Личное', exact: true }).click();
  await page.getByRole('navigation', { name: 'Быстрая навигация' }).getByRole('link', { name: 'Заявки', exact: true }).click();
  await page.locator('.req-open-link').click();
  await expect(page.getByRole('button', { name: 'Согласовать заявку' })).toHaveCount(0);
});

test('server overlap during submission opens the existing request instead of a dead-end error', async ({ page }) => {
  await mockPortal(page, { role: 'worker', records: [request()] });
  await page.route('**/api/v1/requests', async route => {
    if (route.request().method() !== 'POST') return route.fallback();
    return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Leave overlaps an existing pending or approved request' }) });
  });
  await page.goto('/requests/new?type=leave&start=2030-11-03&end=2030-11-06&review=1');
  await page.getByRole('button', { name: 'Отправить заявку', exact: true }).click();
  await expect(page.locator('.req-conflict')).toContainText('Тестовый HR');
  await expect(page.getByRole('button', { name: 'Отправить заявку', exact: true })).toBeDisabled();
  await page.locator('.req-conflict').getByRole('link', { name: 'Открыть заявку' }).click();
  await expect(page).toHaveURL(new RegExp(`/requests/${requestId}$`));
  await expect(page.locator('.req-workflow-summary')).toContainText('Ждёт решения');
});

test('capture request states for visual review', async ({ page }, testInfo) => {
  test.skip(!process.env.POSTTECH_CAPTURE_UI, 'Optional screenshots of synthetic fixtures');
  await mockPortal(page, { records: [request(), request({ id: otherRequestId, employee_id: employeeId, approvers: [approver], can_review: true })] });
  await page.goto('/calendar?select=1&start=2030-11-05&end=2030-11-08');
  await expect(page.locator('.req-conflict')).toBeVisible();
  await page.screenshot({ path: `../docs/design/conflict-${testInfo.project.name}.png`, fullPage: true, animations: 'disabled' });
  await page.goto(`/requests/${otherRequestId}`);
  await expect(page.locator('.req-workflow-summary')).toBeVisible();
  await page.screenshot({ path: `../docs/design/approval-${testInfo.project.name}.png`, fullPage: true, animations: 'disabled' });
  await page.goto('/requests?scope=review');
  await expect(page.locator('.req-table tbody tr')).toHaveCount(1);
  await page.screenshot({ path: `../docs/design/inbox-${testInfo.project.name}.png`, fullPage: true, animations: 'disabled' });
});
