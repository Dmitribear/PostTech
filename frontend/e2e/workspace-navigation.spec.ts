import { expect, test, type Page } from '@playwright/test';

async function demo(page: Page, role: string) {
  await page.addInitScript(role => sessionStorage.setItem('posttech.demo-role', role), role);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Мой кабинет', exact: true })).toBeVisible();
  await expect(page.locator('.desk-request')).toHaveCount(3);
}
const switches = (page: Page) => page.locator(page.viewportSize()!.width <= 900 ? '.workspace-switch-mobile' : '.workspace-switch-desktop');
const nav = (page: Page) => page.getByRole('navigation', { name: page.viewportSize()!.width <= 900 ? 'Быстрая навигация' : 'Главная навигация' });
async function noOverflow(page: Page) { expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true); }

test('minimal employee workspace keeps primary tasks and secondary tools reachable', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await demo(page, 'worker');
  await expect(page.locator('.workspace-switch')).toHaveCount(0);
  await expect(page.locator('.global-search, .home-brand-scene, .home-quick-actions')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Оформить отпуск', exact: true })).toHaveCount(1);
  await expect(page.getByRole('link', { name: 'Оформить отпуск', exact: true })).toHaveAttribute('href', '/calendar?select=1');
  await expect(page.getByRole('link', { name: 'Продолжить', exact: true })).toHaveAttribute('href', /academy\?course=/);
  await noOverflow(page);
  await page.screenshot({ path: `test-results/simple-employee-${info.project.name}.png`, fullPage: true });
  await page.getByLabel('Меню профиля', { exact: true }).click();
  await expect(page.locator('.account-popover').getByRole('link', { name: 'Инструменты HR' })).toHaveCount(0);
  await expect(page.getByLabel('Language / Тіл')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.account-popover')).toBeHidden();
  await page.getByLabel('Меню профиля', { exact: true }).click();
  await page.locator('.account-popover').getByRole('link', { name: 'Календарь', exact: true }).click();
  await expect(page).toHaveURL(/\/calendar$/);
  await expect(page.locator('.account-popover')).toBeHidden();
  await page.goto('/hr-tools');
  await expect(page).toHaveURL(/\/$/);
  await page.setViewportSize({ width: 320, height: 780 });
  await noOverflow(page);
  expect(errors).toEqual([]);
});

test('manager switches between personal leave and approval queue without mixing scope', async ({ page }, info) => {
  await demo(page, 'manager');
  await switches(page).getByRole('button', { name: 'Команда', exact: true }).click();
  await expect(page).toHaveURL(/scope=review/);
  await expect(page.getByRole('heading', { name: 'На согласование', exact: true })).toBeVisible();
  await expect(page.locator('.req-stat-grid, .req-scope-switch')).toHaveCount(0);
  await expect(page.locator('.req-open-link').first()).toBeVisible();
  await noOverflow(page);
  await page.screenshot({ path: `test-results/simple-manager-${info.project.name}.png`, fullPage: true });
  await page.locator('.req-open-link').first().click();
  await page.reload();
  await expect(switches(page).getByRole('button', { name: 'Команда', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await switches(page).getByRole('button', { name: 'Личное', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Оформить отпуск', exact: true })).toBeVisible();
  await nav(page).getByRole('link', { name: 'Заявки', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Мои заявки', exact: true })).toBeVisible();
});

test('HR employee list opens details and all administrative tools remain available', async ({ page }, info) => {
  await demo(page, 'hr_admin');
  await switches(page).getByRole('button', { name: 'HR', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Сотрудники', exact: true })).toBeVisible();
  await expect(page.locator('.people-person').first()).toBeVisible();
  await expect(page.locator('.people-page>.support-metrics')).toHaveCount(0);
  await noOverflow(page);
  await page.screenshot({ path: `test-results/simple-hr-${info.project.name}.png`, fullPage: true });
  await page.getByRole('textbox', { name: 'Поиск сотрудника', exact: true }).fill('Алия Серикова');
  await expect(page.locator('.people-row')).toHaveCount(1);
  await page.locator('.people-person').click();
  await expect(page.getByRole('dialog').getByRole('button', { name: 'Назначить курс', exact: true })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.getByLabel('Меню профиля', { exact: true }).click();
  await page.locator('.account-popover').getByRole('link', { name: 'Инструменты HR', exact: true }).click();
  for (const target of ['/operations', '/delegations', '/course-editor', '/support']) await expect(page.locator(`.workspace-links a[href="${target}"]`)).toBeVisible();
  await page.reload();
  await expect(switches(page).getByRole('button', { name: 'HR', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await noOverflow(page);
});
