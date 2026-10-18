import { expect, test } from '@playwright/test';
import { mockPlans } from './fixtures/calendar-plans';

for (const role of ['worker', 'manager'] as const) {
  test(`${role}: all leave pages and course deadlines update in the open day without reload`, async ({
    page,
  }, testInfo) => {
    test.setTimeout(60_000);
    if (testInfo.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 844 });
    const state = await mockPlans(page, role);
    await page.goto('/');
    const calendar = page.getByRole('region', { name: 'Календарь на главной' });
    const day = (key: string) => calendar.locator(`button[data-day="${key}"]`);
    await expect(day('2026-11-01')).toHaveClass(/has-leave/);
    await expect(day('2026-11-01')).toHaveClass(/has-course/);
    await expect(day('2026-10-27')).toHaveClass(/has-pending/);
    expect(state.pages).toContain(100);
    await calendar.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('calendar-plans.png') });
    await day('2026-11-01').click();
    const details = page.getByRole('dialog');
    await expect(details.locator('.desk-day-event')).toHaveCount(3);
    await expect(details).not.toContainText('Завершённый курс');
    await expect(
      details.getByRole('link', { name: 'Открыть заявку', exact: true }),
    ).toHaveAttribute('href', `/requests/${state.active.id}`);
    await expect(
      details.getByRole('link', { name: 'Открыть курс', exact: true }).first(),
    ).toHaveAttribute('href', `/academy?course=${state.courses[0].course!.id}`);
    expect(await details.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('day-details.png') });
    state.active.status = 'cancelled';
    state.courses[0].due_on = '2026-11-02';
    state.courses[1].status = 'completed';
    state.pending.status = 'approved';
    await expect(details).toContainText('На этот день ничего не запланировано');
    await expect(details.locator('.desk-day-event')).toHaveCount(0);
    await details.getByRole('button', { name: 'Закрыть', exact: true }).click();
    await expect(day('2026-11-01')).not.toHaveClass(/has-leave|has-course/);
    await expect(day('2026-10-27')).toHaveClass(/has-leave/);
    await expect(day('2026-10-27')).not.toHaveClass(/has-pending/);
    await calendar.getByRole('button', { name: 'Следующий месяц' }).click();
    await expect(day('2026-11-02')).toHaveClass(/has-course/);
    await day('2026-11-02').click();
    await expect(details.locator('.desk-day-event')).toHaveCount(1);
    await expect(details).toContainText(state.courses[0].course!.title);
    expect(await page.evaluate(() => sessionStorage.getItem('calendar-loads'))).toBe('1');
  });
}
