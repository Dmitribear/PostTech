import { expect, test } from '@playwright/test';
import { mockPlans } from './fixtures/calendar-plans';

test('personal course form saves link, deadline and progress and opens from calendar', async ({
  page,
}, info) => {
  if (info.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 844 });
  const state = await mockPlans(page, 'worker');
  state.courses.splice(0);
  let calls = 0;
  await page.route('**/api/v1/academy/courses', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/v1/academy/personal-courses', async (route) => {
    calls++;
    const input = route.request().postDataJSON();
    expect(input).toMatchObject({
      title: 'Аналитика для логистики',
      provider: 'Яндекс Практикум',
      external_url: 'https://example.com/analytics',
      due_on: '2026-11-01',
      progress_percent: 35,
    });
    const assignment = {
      id: 'new-assignment',
      course_id: input.id,
      employee_id: state.profile.id,
      assigned_by: state.profile.id,
      assigned_at: new Date().toISOString(),
      completed_at: null,
      status: 'in_progress' as const,
      progress_percent: input.progress_percent,
      score_percent: null,
      due_on: input.due_on,
    };
    state.courses.push({
      ...assignment,
      course: {
        ...input,
        description: '',
        duration_minutes: 0,
        course_type: 'external',
        owner_employee_id: state.profile.id,
      },
    });
    await route.fulfill({ json: assignment, status: 201 });
  });
  await page.goto('/academy');
  await page.getByRole('button', { name: 'Свой курс', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Ссылка на курс', { exact: true }).fill('http://example.com/analytics');
  await dialog.getByLabel('Название курса', { exact: true }).fill('Аналитика для логистики');
  await dialog.getByLabel('Площадка', { exact: true }).fill('Яндекс Практикум');
  await dialog.getByLabel('Пройти до', { exact: true }).fill('2026-11-01');
  await dialog.getByLabel('Пройдено, %', { exact: true }).fill('35');
  await dialog.getByRole('button', { name: 'Добавить курс', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('https://');
  expect(calls).toBe(0);
  await dialog.getByLabel('Ссылка на курс', { exact: true }).fill('https://example.com/analytics');
  await page.screenshot({ path: info.outputPath('personal-course-form.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await dialog.getByRole('button', { name: 'Добавить курс', exact: true }).click();
  await expect(dialog.getByRole('heading', { name: 'Аналитика для логистики' })).toBeVisible();
  await expect(dialog.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '35');
  expect(calls).toBe(1);
  await page.goto('/calendar?date=2026-11-01');
  const details = page.getByRole('region', { name: 'События дня' });
  await expect(details).toContainText('Аналитика для логистики');
  await details.getByRole('link', { name: 'Открыть курс' }).click();
  await expect(dialog.getByRole('link', { name: 'Открыть на площадке' })).toHaveAttribute(
    'href',
    'https://example.com/analytics',
  );
});

test('dashboard stacks learning below requests with a full-width help footer', async ({
  page,
}, info) => {
  if (info.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 844 });
  const state = await mockPlans(page, 'worker');
  state.courses.splice(0);
  await page.route('**/api/v1/requests?*', (route) => route.fulfill({ json: [] }));
  await page.goto('/');
  await expect(page.locator('.desk-learning')).toBeVisible();
  const requests = (await page.locator('.desk-requests').boundingBox())!;
  const learning = (await page.locator('.desk-learning').boundingBox())!;
  const calendar = (await page.locator('.desk-calendar').boundingBox())!;
  const help = (await page.locator('.desk-help').boundingBox())!;
  const grid = (await page.locator('.desk-grid').boundingBox())!;
  expect(learning.y - requests.y - requests.height).toBeLessThan(24);
  expect(help.width).toBeCloseTo(grid.width, 0);
  expect(help.y).toBeGreaterThanOrEqual(
    Math.max(calendar.y + calendar.height, learning.y + learning.height),
  );
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: info.outputPath('dashboard-personal-learning.png'),
    fullPage: true,
  });
  await page.locator('.desk-learning').getByRole('link', { name: 'Добавить свой курс' }).click();
  await expect(page.getByRole('dialog', { name: 'Свой курс' })).toBeVisible();
  await page.goto('/jana');
  await expect(page.locator('.lucide-sparkles, .lucide-bot')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Чем помочь?' })).toBeVisible();
});
