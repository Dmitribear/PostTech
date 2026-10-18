import { expect, test, type Page } from '@playwright/test';

async function enterDemo(page: Page) {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Демо-вход', exact: true }).click();
  await page.getByRole('radio', { name: /^Сотрудник/ }).check();
  await page.getByRole('button', { name: 'Открыть демо', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Календарь на главной' })).toBeVisible();
}

test('home calendar changes year and opens day details in one click', async ({
  page,
}, testInfo) => {
  await page.clock.setFixedTime(new Date('2026-12-15T10:00:00+05:00'));
  await enterDemo(page);
  const calendar = page.getByRole('region', { name: 'Календарь на главной' });
  await expect(calendar.locator('[aria-current="date"]')).toHaveAttribute('data-day', '2026-12-15');
  await expect(calendar.locator('.desk-calendar-title')).toContainText('декабрь 2026');
  await calendar.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('home-calendar.png') });
  await calendar.getByRole('button', { name: 'Следующий месяц' }).click();
  await expect(calendar.locator('.desk-calendar-title')).toContainText('январь 2027');
  await expect(page).toHaveURL(/\/$/);
  await calendar.locator('button[data-day="2027-01-10"]').click();
  await expect(page).toHaveURL(/\/$/);
  const details = page.getByRole('dialog');
  await expect(details).toContainText('На этот день ничего не запланировано');
  await details.getByRole('link', { name: 'Открыть календарь', exact: true }).click();
  await expect(page).toHaveURL(/\/calendar\?date=2027-01-10$/);
  await expect(page.locator('.cal-day.selected')).toHaveAttribute('data-day', '2027-01-10');
});

test('home calendar supports leap days, today reset and narrow screens', async ({
  page,
}, testInfo) => {
  if (testInfo.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 844 });
  await page.clock.setFixedTime(new Date('2028-02-10T10:00:00+05:00'));
  await enterDemo(page);
  const calendar = page.getByRole('region', { name: 'Календарь на главной' });
  await calendar.getByRole('button', { name: 'Предыдущий месяц' }).click();
  await expect(calendar.locator('.desk-calendar-title')).toContainText('январь 2028');
  await calendar.getByRole('button', { name: 'Сегодня', exact: true }).click();
  await expect(calendar.locator('.desk-calendar-title')).toContainText('февраль 2028');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(
    await calendar.locator('.desk-calendar-day').evaluateAll((days) =>
      days.every((day) => {
        const box = day.getBoundingClientRect();
        return box.width >= 32 && box.height >= 44 && box.left >= 0 && box.right <= innerWidth;
      }),
    ),
  ).toBe(true);
  const leapDay = calendar.locator('button[data-day="2028-02-29"]');
  await leapDay.focus();
  await leapDay.press('Enter');
  await expect(
    page.getByRole('dialog').getByRole('link', { name: 'Открыть календарь', exact: true }),
  ).toHaveAttribute('href', '/calendar?date=2028-02-29');
});
