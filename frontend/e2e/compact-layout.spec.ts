import { expect, test, type Locator, type Page } from '@playwright/test';

async function enterDemo(page: Page, manager = false) {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Демо-вход', exact: true }).click();
  await page.getByRole('radio', { name: manager ? /^Руководитель/ : /^Сотрудник/ }).check();
  await page.getByRole('button', { name: 'Открыть демо', exact: true }).click();
  await expect(page.locator('#main-content h1')).toBeVisible();
}

async function fitsHorizontally(locator: Locator) {
  expect(
    await locator.evaluateAll((nodes) =>
      nodes
        .filter((node) => {
          const box = node.getBoundingClientRect();
          return (
            box.width &&
            (box.left < -1 || box.right > innerWidth + 1 || node.scrollWidth > node.clientWidth + 1)
          );
        })
        .map((node) => node.className),
    ),
  ).toEqual([]);
}

for (const width of [320, 390, 768, 1440]) {
  test(`course reader and team rows fit ${width}px`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await page.setViewportSize({ width, height: 900 });
    await enterDemo(page, true);
    await page.goto('/academy?tab=team');
    const rows = page.locator('.academy-team-row');
    await expect(rows.first()).toBeVisible();
    const completed = rows.filter({ has: page.locator('.badge-completed') }).first();
    await expect(completed).toContainText('Завершён');
    await expect(completed).not.toContainText('Изучает материал');
    await completed.locator('summary').click();
    await expect(completed.locator('dl')).toBeVisible();
    await fitsHorizontally(
      page.locator('html, .academy-team-row, .academy-team-row > div, .academy-team-row dl'),
    );
    await page.screenshot({ path: testInfo.outputPath(`team-${width}.png`) });
    await page.goto('/academy?tab=all');
    const course = page
      .locator('article')
      .filter({
        has: page.getByRole('heading', { name: 'Эффективная работа в команде', exact: true }),
      });
    await course.getByRole('button').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.locator('.academy-course-facts summary').click();
    await expect(dialog.locator('.academy-course-facts')).toContainText('80%');
    await fitsHorizontally(
      page.locator(
        'dialog, .modal-heading, .modal-heading-copy, .support-course-reader, .support-material',
      ),
    );
    const heading = await dialog.locator('h2').first().boundingBox();
    const close = await dialog.getByRole('button', { name: 'Закрыть', exact: true }).boundingBox();
    expect(heading!.x + heading!.width).toBeLessThanOrEqual(close!.x);
    await page.screenshot({ path: testInfo.outputPath(`course-${width}.png`) });
    await dialog.getByRole('button', { name: 'Закрыть', exact: true }).click();
    await expect(dialog).toBeHidden();
  });

  test(`request status does not overlap date or title at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await enterDemo(page);
    await expect(page.locator('.desk-request').first()).toBeVisible();
    await fitsHorizontally(page.locator('html, .desk-request:visible'));
    expect(
      await page.locator('.desk-request:visible').evaluateAll((rows) =>
        rows.flatMap((row) => {
          const status = row.querySelector('.badge')?.getBoundingClientRect();
          if (!status) return ['missing status'];
          return [...row.querySelectorAll('.desk-request-period, .desk-request-name strong')]
            .filter((el) => {
              const box = el.getBoundingClientRect();
              return (
                Math.min(box.right, status.right) - Math.max(box.left, status.left) > 1 &&
                Math.min(box.bottom, status.bottom) - Math.max(box.top, status.top) > 1
              );
            })
            .map((el) => el.textContent);
        }),
      ),
    ).toEqual([]);
  });
}
