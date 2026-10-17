import { expect, test, type Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import type { AppRole, HrRequest } from '../src/lib/types';

const actor = '80000000-0000-4000-8000-000000000001';
const worker = '80000000-0000-4000-8000-000000000002';
const requestId = '80000000-0000-4000-8000-000000000101';
const sourceId = '80000000-0000-4000-8000-000000000201';
const stamp = '2026-10-17T10:00:00Z';
const excerpt = 'При окончательном одобрении HR отпускные дни списываются из кадрового остатка.';
const calendar = 'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261110\r\nDTEND;VALUE=DATE:20261113\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n';

async function portal(page: Page, role: AppRole, status: HrRequest['status'] = 'pending') {
  const record: HrRequest = { id: requestId, employee_id: worker, request_type: 'leave', status, start_date: '2026-11-10', end_date: '2026-11-12', amount: null, comment: 'Плановый отпуск', reviewer_comment: null, reviewed_by: null, reviewed_at: null, created_at: stamp, updated_at: stamp, can_review: true, approval_route: status === 'pending_hr' ? 'hr' : 'manager', approvers: [{ id: actor, full_name: 'Тестовый согласующий', role: role === 'worker' ? 'hr_admin' : role }] };
  const writes: string[] = [];
  const sources: string[] = [];
  await page.addInitScript(() => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({ user_id: 'mock-user', email: 'test@example.test', access_token: 'mock-token', refresh_token: 'mock-refresh', token_type: 'bearer', expires_in: 3600, expires_at: Date.now() + 3600000 })));
  await page.route('**/api/v1/**', async route => {
    const req = route.request(); const url = new URL(req.url()); const path = url.pathname.replace('/api/v1', '');
    const respond = (value: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
    expect(req.headers().authorization).toBe('Bearer mock-token');
    const profile = { id: actor, employee_code: 'TEST-1', full_name: 'Тестовый согласующий', email: 'test@example.test', company: 'PostTech', job_title: 'Проверка', department: 'Команда', manager_id: null, hired_at: '2024-01-01', vacation_days_remaining: 24, role, external_source: 'test', created_at: stamp, updated_at: stamp };
    if (path === '/profile') return respond(profile);
    if (path === '/team') return respond([{ ...profile, id: worker, full_name: 'Тестовый сотрудник', role: 'worker', manager_id: actor }, { ...profile, id: 'manager-candidate', full_name: 'Руководитель команды', role: 'manager' }, { ...profile, id: 'director-candidate', full_name: 'Директор команды', role: 'director' }, profile]);
    if (path === '/workspace/leave-balance') return respond({ employee_id: worker, official_days: 24, pending_days: 3, approved_unreconciled_days: 0, available_days: 21, request_days: 3, holds: [] });
    if (path === '/requests') return respond([record]);
    if (path === `/requests/${requestId}/review`) {
      writes.push(path); const body = req.postDataJSON();
      record.status = body.status === 'approved' && role !== 'hr_admin' ? 'pending_hr' : body.status;
      record.can_review = false;
      record.approvers = [{ id: '80000000-0000-4000-8000-000000000003', full_name: 'Отдел HR', role: 'hr_admin' }];
      record.reviewer_comment = body.reviewer_comment;
      return respond(record);
    }
    if (path === `/requests/${requestId}/history`) return respond([]);
    if (path === `/requests/${requestId}/calendar.ics`) {
      expect(record.status).toBe('approved');
      return route.fulfill({ contentType: 'text/calendar; charset=utf-8', body: calendar });
    }
    if (path === `/requests/${requestId}`) return respond(record);
    if (path === '/ai/ask') {
      const question = req.postDataJSON().question;
      if (question === 'Уточнение') return respond({ answer: 'О какой заявке идёт речь?', sources: [], grounded: false, escalation_suggested: false, mode: 'refusal' });
      if (question === 'Неизвестный факт') return respond({ answer: 'В базе знаний нет подтверждённого ответа.', sources: [], grounded: false, escalation_suggested: true, mode: 'refusal' });
      return respond({ answer: excerpt, sources: [{ id: sourceId, title: 'Порядок согласования', url: `/api/v1/ai/sources/${sourceId}`, version: 'snapshot-test', excerpt }], grounded: true, escalation_suggested: false, mode: 'excerpt' });
    }
    if (path === `/ai/sources/${sourceId}`) {
      sources.push(url.search);
      return respond({ id: sourceId, title: 'Согласование отпуска', source_title: 'Порядок согласования', source_url: null, content: `${excerpt}\nОтпуск до одобрения остаётся на согласовании.`, version: 'snapshot-test', freshness: 'reviewed', reviewed_at: stamp });
    }
    return respond([]);
  });
  return { record, writes, sources };
}

test('director forwards leave to HR without falsely showing final approval or calendar export', async ({ page }) => {
  const { writes } = await portal(page, 'director');
  await page.goto(`/requests/${requestId}`);
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toBeVisible();
  await page.getByRole('button', { name: 'Согласовать заявку', exact: true }).click();
  await page.getByRole('button', { name: 'Подтвердить решение', exact: true }).click();
  await expect(page.locator('.req-detail-actions')).toContainText('На согласовании HR');
  await expect(page.locator('.toast')).toContainText('окончательного решения');
  await expect(page.getByRole('button', { name: 'Скачать отпуск (.ics)' })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Рассмотрение заявки' })).toHaveCount(0);
  expect(writes).toHaveLength(1);
});

test('HR queue includes pending_hr and final approval exposes an inclusive calendar file', async ({ page }) => {
  await portal(page, 'hr_admin', 'pending_hr');
  await page.goto('/requests?scope=review');
  await expect(page.locator('.req-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.req-table')).toContainText('На согласовании HR');
  await page.locator('.req-table-title').click();
  await page.getByRole('button', { name: 'Согласовать заявку', exact: true }).click();
  await page.getByRole('button', { name: 'Подтвердить решение', exact: true }).click();
  await expect(page.locator('.req-detail-actions')).toContainText('Одобрено');
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать отпуск (.ics)' }).click();
  const download = await downloading;
  expect(download.suggestedFilename()).toBe(`leave-${requestId}.ics`);
  expect(await readFile((await download.path())!, 'utf-8')).toBe(calendar);
});

test('local Jana contract opens the quoted source version and distinguishes clarification from escalation', async ({ page }) => {
  const { sources } = await portal(page, 'worker');
  await page.goto('/jana');
  await page.getByRole('button', { name: 'Как оформить отпуск?', exact: true }).click();
  const log = page.getByRole('log');
  await expect(log).toContainText(excerpt);
  await page.getByRole('button', { name: 'Порядок согласования' }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Фрагмент из ответа' })).toBeVisible();
  await expect(dialog.locator('blockquote')).toHaveText(excerpt);
  await expect(dialog.locator('.source-document')).toContainText('до одобрения');
  expect(sources).toEqual(['?version=snapshot-test']);
  await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Уточнение');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  await expect(log).toContainText('О какой заявке идёт речь?');
  await expect(log.getByRole('button', { name: 'Передать вопрос в HR' })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Неизвестный факт');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  await expect(log).toContainText('нет подтверждённого ответа');
  await expect(log.getByRole('button', { name: 'Передать вопрос в HR' })).toHaveCount(1);
});


test('HR configures delegation only between managers and directors', async ({ page }) => {
  await portal(page, 'hr_admin');
  await page.goto('/delegations');
  await expect(page.getByRole('heading', { name: 'Замещения не назначены' })).toBeVisible();
  await page.getByRole('button', { name: 'Назначить заместителя', exact: true }).click();
  const dialog = page.getByRole('dialog');
  const manager = dialog.getByLabel('Кого замещаем');
  const deputy = dialog.getByLabel('Заместитель', { exact: true });
  await expect(manager.locator('option')).toHaveCount(3);
  await expect(manager).toContainText('Руководитель команды');
  await expect(manager).toContainText('Директор команды');
  await expect(manager).not.toContainText('Тестовый согласующий');
  await expect(manager).not.toContainText('Тестовый сотрудник');
  await manager.selectOption('manager-candidate');
  await expect(deputy.locator('option')).toHaveCount(2);
  await expect(deputy).toContainText('Директор команды');
  await expect(deputy).not.toContainText('Руководитель команды');
  await expect(dialog).toContainText('Окончательное решение остаётся за HR');
});
