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

test('owner sees saved HR route and cancels only after confirmation', async ({ page }) => {
  const { writes } = await mockPortal(page, { records: [request()] });
  await page.goto(`/requests/${requestId}`);
  await expect(page.locator('.req-routing-card')).toContainText('Тестовый HR');
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toHaveCount(0);
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
  await expect(proceed).toBeDisabled();
  await start.fill('2030-11-07'); await end.fill('2030-11-08');
  await expect(proceed).toBeEnabled();
  await proceed.click();
  await expect(page).toHaveURL(/start=2030-11-07&end=2030-11-08/);
  await expect(page.getByRole('heading', { name: 'Проверьте заявку' })).toBeVisible();
  await expect(page.locator('.req-review-hero')).toContainText('7 нояб. 2030');
  await expect(page.locator('.req-review-approver')).toContainText('Тестовый HR');
  await expect(page.getByRole('button', { name: 'Отправить заявку', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Изменить', exact: true }).click();
  await expect(page.getByLabel('Дата начала', { exact: true })).toHaveValue('2030-11-07');
});
