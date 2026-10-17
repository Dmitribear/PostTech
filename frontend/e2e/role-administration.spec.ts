import { expect, test } from '@playwright/test';

test('HR changes a role in the employee card, preserving the reporting line guard', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('posttech.demo-role', 'hr_admin'));
  await page.goto('/team');
  await page.getByRole('button', {name: 'Профиль: Дарья Ким'}).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Роль в системе').selectOption('director');
  await dialog.getByRole('button', {name: 'Сохранить роль'}).click();
  await expect(dialog.getByLabel('Роль в системе')).toHaveValue('director');
  await expect(dialog.getByRole('button', {name: 'Сохранить роль'})).toHaveCount(0);
  await dialog.getByRole('button', {name: 'Закрыть', exact: true}).click();
  await page.getByRole('button', {name: 'Профиль: Ерлан Касымов'}).click();
  await dialog.getByLabel('Роль в системе').selectOption('worker');
  await dialog.getByRole('button', {name: 'Сохранить роль'}).click();
  await expect(dialog.getByRole('alert')).toContainText('Сначала назначьте подчинённым другого руководителя');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
