import { expect, test, type Page, type Route } from '@playwright/test';

const employeeId = '40000000-0000-4000-8000-000000000001';
const requestId = '40000000-0000-4000-8000-000000000002';
const sourceId = '40000000-0000-4000-8000-000000000003';
const quote = 'Отпуск оформляется заявкой с датами начала и окончания.';
const source = { id: sourceId, title: 'Порядок оформления отпуска', url: 'https://untrusted.invalid/do-not-follow', excerpt: quote };
const respond = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function livePortal(page: Page, handler: (route: Route, path: string) => Promise<boolean>) {
  await page.addInitScript(() => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({ user_id: 'test-user', email: 'test@example.test', access_token: 'test-token', refresh_token: 'test-refresh', token_type: 'bearer', expires_in: 3600, expires_at: Date.now() + 3600_000 })));
  await page.route('**/api/v1/**', async route => {
    expect(route.request().headers().authorization).toBe('Bearer test-token');
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (await handler(route, path)) return;
    if (path.startsWith('/workspace/fulfillment/')) return respond(route, {status:'awaiting_hr', note:'', can_send:false, deliveries:[], events:[]});
    if (path === '/profile') return respond(route, { id: employeeId, employee_code: 'TEST-01', full_name: 'Тестовый Сотрудник', email: 'test@example.test', company: 'PostTech', job_title: 'Оператор', department: 'Хаб', manager_id: null, hired_at: '2023-01-10', vacation_days_remaining: 24, role: 'worker', external_source: 'test', created_at: '2026-01-01T10:00:00Z', updated_at: '2026-10-01T10:00:00Z' });
    return respond(route, []);
  });
}

test('live Jana opens authenticated sources, shows refusals and retains questions on model failure', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  let sourceMissing = false;
  let askCount = 0;
  await livePortal(page, async (route, path) => {
    if (path === '/ai/ask') {
      askCount++;
      const question = route.request().postDataJSON().question;
      if (question === 'Недоступная модель') await respond(route, { detail: 'Jana AI is temporarily unavailable' }, 503);
      else if (question === 'Расскажи про погоду') await respond(route, { answer: 'В базе нет подтверждённой информации.', sources: [], grounded: false, escalation_suggested: true, mode: 'refusal' });
      else await respond(route, { answer: quote, sources: [source], grounded: true, escalation_suggested: false, mode: 'excerpts' });
      return true;
    }
    if (path === `/ai/sources/${sourceId}`) {
      await respond(route, sourceMissing ? { detail: 'Source not found' } : { id: sourceId, title: source.title, content: `${quote}\nЭто полный проверяемый материал.\n<script>alert('not executed')</script>`, source_title: 'Тестовый HR-документ', source_url: null }, sourceMissing ? 404 : 200);
      return true;
    }
    return false;
  });
  await page.goto('/jana');
  await page.getByRole('button', { name: 'Как оформить отпуск?', exact: true }).click();
  await expect(page.locator('.support-answer-text')).toHaveText(quote);
  await page.getByRole('button', { name: source.title, exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Это полный проверяемый материал.');
  await expect(page.getByRole('dialog')).toContainText('<script>');
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)).toBe(false);
  await page.screenshot({ path: `test-results/jana-source-${testInfo.project.name}.png`, fullPage: true });
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  sourceMissing = true;
  await page.getByRole('button', { name: source.title, exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('больше не опубликован');
  sourceMissing = false;
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Это полный проверяемый материал.');
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Расскажи про погоду');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  await expect(page.locator('.support-message.jana').last()).toContainText('нет подтверждённой информации');
  await expect(page.locator('.support-message.jana').last().locator('.support-citation')).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Недоступная модель');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  await expect(page.getByRole('alert')).toContainText('Jana сейчас недоступна');
  await expect(page.getByRole('textbox', { name: 'Ваш вопрос Jana' })).toHaveValue('Недоступная модель');
  await expect(page.locator('.support-message.jana')).toHaveCount(2);
  expect(askCount).toBe(3);
  expect(errors).toEqual([]);
});

test('approved leave downloads authenticated ICS, and changed status remains an error', async ({ page }) => {
  let status = 'approved';
  let rejectExport = false;
  const ics = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261231\r\nDTEND;VALUE=DATE:20270101\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n';
  await livePortal(page, async (route, path) => {
    if (path === `/requests/${requestId}`) {
      await respond(route, { id: requestId, employee_id: employeeId, request_type: 'leave', status, start_date: '2026-12-31', end_date: '2026-12-31', comment: null, amount: null, created_at: '2026-10-16T10:00:00Z', updated_at: '2026-10-16T10:00:00Z', reviewer_comment: null, reviewed_by: null, reviewed_at: null });
      return true;
    }
    if (path.endsWith('/calendar.ics')) {
      if (rejectExport) await respond(route, { detail: 'Calendar export requires an approved leave request' }, 409);
      else await route.fulfill({ contentType: 'text/calendar; charset=utf-8', body: ics });
      return true;
    }
    return false;
  });
  await page.goto(`/requests/${requestId}`);
  const downloadReady = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать отпуск (.ics)' }).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe(`leave-${requestId}.ics`);
  const stream = await download.createReadStream();
  let contents = '';
  for await (const chunk of stream!) contents += chunk.toString();
  expect(contents).toBe(ics);
  await expect(page.locator('#main-content')).toContainText('Импорт выполняется вручную');
  rejectExport = true;
  await page.getByRole('button', { name: 'Скачать отпуск (.ics)' }).click();
  await expect(page.getByRole('alert')).toContainText('только для одобренного отпуска');
  status = 'pending';
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Заявка на отпуск', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Скачать отпуск (.ics)' })).toHaveCount(0);
});
