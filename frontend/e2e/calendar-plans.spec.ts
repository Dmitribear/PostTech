import { expect, test } from '@playwright/test';
import { mockPlans } from './fixtures/calendar-plans';

test('home and full calendar agree, refresh deadlines, and open courses and requests', async ({
  page,
}, testInfo) => {
  test.setTimeout(60_000);
  const mobile = testInfo.project.name === 'mobile';
  if (mobile) await page.setViewportSize({ width: 320, height: 844 });
  const state = await mockPlans(page, 'worker');
  await page.goto('/');
  const home = page.getByRole('region', { name: 'Календарь на главной' });
  await home.locator('[data-day="2026-11-01"]').click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('.desk-day-event')).toHaveCount(3);
  await dialog.getByRole('link', { name: 'Открыть календарь', exact: true }).click();
  const day = (date: string) => page.locator(`.cal-day[data-day="${date}"]`);
  const details = page.getByRole('region', { name: 'События дня' });
  await expect(day('2026-11-01')).toHaveClass(/has-course/);
  await expect(day('2026-11-01')).toHaveClass(/has-approved/);
  await expect(details.locator('.cal-selected-event')).toHaveCount(3);
  await expect(details).toContainText(state.courses[0].course!.title);
  await expect(details).not.toContainText('Завершённый курс');
  await expect(details.getByRole('link', { name: 'Открыть курс', exact: true })).toHaveCount(2);
  if (!mobile) {
    await day('2026-11-02').locator('.cal-day-select').click();
    await day('2026-11-01').getByRole('button', { name: /Ещё/ }).click();
    await expect(details.locator('.cal-selected-event')).toHaveCount(3);
  } else {
    await day('2026-11-01').locator('.cal-day-select').click();
  }
  if (mobile) await details.scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('full-calendar-events.png') });

  state.active.status = 'cancelled';
  state.courses[0].due_on = '2026-11-02';
  state.courses[1].status = 'completed';
  await expect(details).toContainText('На этот день ничего не запланировано');
  await expect(day('2026-11-01')).not.toHaveClass(/has-course|has-approved/);
  await expect(day('2026-11-02')).toHaveClass(/has-course/);
  if (mobile) {
    await day('2026-11-02').getByRole('button').click();
    await expect(details.locator('.cal-selected-event')).toHaveCount(1);
    await details.getByRole('link', { name: 'Открыть курс', exact: true }).click();
  } else {
    await day('2026-11-02')
      .getByRole('link', { name: /^Открыть курс:/ })
      .click();
  }
  await expect(page).toHaveURL(new RegExp(`/academy\\?course=${state.courses[0].course!.id}`));
  await expect(page.getByRole('dialog')).toContainText(state.courses[0].course!.title);
  await page.goBack();
  if (mobile) {
    await day('2026-10-27').getByRole('button').click();
    await details.getByRole('link', { name: /^Открыть REQ-/ }).click();
  } else {
    await day('2026-10-27')
      .getByRole('link', { name: /^Открыть заявку:/ })
      .click();
  }
  await expect(page).toHaveURL(new RegExp(`/requests/${state.pending.id}$`));
  await expect(page.locator('.req-detail-summary')).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem('calendar-loads'))).toBe('1');
});

test('team calendar does not mix in personal course deadlines', async ({ page }) => {
  await mockPlans(page, 'manager');
  await page.goto('/calendar?date=2026-11-01');
  const day = page.locator('.cal-day[data-day="2026-11-01"]');
  await expect(day).toHaveClass(/has-course/);
  await page.locator('.cal-scope').getByRole('button', { name: 'Команда', exact: true }).click();
  await expect(day).not.toHaveClass(/has-course/);
  await expect(page.locator('.cal-selected-course')).toHaveCount(0);
  await page
    .locator('.cal-scope')
    .getByRole('button', { name: 'Мой календарь', exact: true })
    .click();
  await expect(day).toHaveClass(/has-course/);
  await expect(page.locator('.cal-selected-course')).toHaveCount(2);
});
