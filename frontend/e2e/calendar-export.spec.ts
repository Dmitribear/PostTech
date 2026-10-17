import { test, expect, type Route } from '@playwright/test';

const ics =
  'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nUID:approved-cross-month@janapost\r\nDTSTART;VALUE=DATE:20261030\r\nDTEND;VALUE=DATE:20261104\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n';
const reply = (route: Route, value: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });

test('calendar exports its month and scope, explains manual import, and never downloads an error', async ({
  page,
}, info) => {
  if (info.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 780 });
  await page.addInitScript(() =>
    sessionStorage.setItem(
      'jana.hr.session.v1',
      JSON.stringify({
        user_id: 'calendar-user',
        email: 'calendar@example.test',
        access_token: 'calendar-token',
        refresh_token: 'refresh',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: Date.now() + 3600000,
      }),
    ),
  );
  const exports: string[] = [];
  let unavailable = false;
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url()),
      path = url.pathname.replace('/api/v1', '');
    if (path === '/profile')
      return reply(route, {
        id: 'calendar-user',
        full_name: 'Тестовый руководитель',
        email: 'calendar@example.test',
        role: 'manager',
        company: 'PostTech',
        job_title: 'Руководитель',
        department: 'Склад',
        vacation_days_remaining: 24,
      });
    if (path === '/requests/calendar.ics') {
      expect(route.request().headers().authorization).toBe('Bearer calendar-token');
      exports.push(url.search);
      if (unavailable) return reply(route, { detail: 'Экспорт временно недоступен.' }, 503);
      return route.fulfill({ contentType: 'text/calendar; charset=utf-8', body: ics });
    }
    return reply(route, []);
  });
  await page.goto('/calendar?date=2026-11-01');
  await page.getByRole('button', { name: 'Экспорт в Google Calendar', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Экспорт в Google Calendar', exact: true });
  await expect(dialog).toContainText('Мой календарь');
  await expect(dialog).toContainText('ноябрь 2026');
  await expect(dialog).toContainText('без автоматической синхронизации');
  await expect(dialog).toContainText('повторный импорт может создать дубликаты');
  const ready = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Скачать календарь (.ics)', exact: true }).click();
  const download = await ready;
  expect(download.suggestedFilename()).toBe('janapost-mine-2026-11.ics');
  let contents = '';
  for await (const chunk of (await download.createReadStream())!) contents += chunk.toString();
  expect(contents).toBe(ics);
  expect(exports[0]).toBe('?scope=mine&start_date=2026-11-01&end_date=2026-11-30');
  await expect(dialog.getByRole('status')).toContainText('Файл скачан');
  await dialog.getByRole('radio', { name: 'Все доступные отпуска', exact: true }).check();
  await expect(dialog).toContainText('Права доступа проверяет сервер');
  const allReady = page.waitForEvent('download');
  await dialog.getByRole('button', { name: 'Скачать календарь (.ics)', exact: true }).click();
  expect((await allReady).suggestedFilename()).toBe('janapost-all-leaves.ics');
  expect(exports[1]).toBe('?scope=all');

  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(
    false,
  );
  await page.keyboard.press('Escape');
  await page.locator('#main-content').getByRole('button', { name: 'Команда', exact: true }).click();
  await page.getByRole('button', { name: 'Следующий месяц', exact: true }).click();
  await page.getByRole('button', { name: 'Экспорт в Google Calendar', exact: true }).click();
  await expect(dialog).toContainText('Команда');
  await expect(dialog).toContainText('декабрь 2026');
  unavailable = true;
  let unexpectedDownload = false;
  page.on('download', () => {
    unexpectedDownload = true;
  });
  await dialog.getByRole('button', { name: 'Скачать календарь (.ics)', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Экспорт временно недоступен');
  expect(exports[2]).toBe('?scope=team&start_date=2026-12-01&end_date=2026-12-31');
  expect(unexpectedDownload).toBe(false);
});
