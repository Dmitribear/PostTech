import { expect, test, type Page, type Route } from '@playwright/test';

const reply = (route: Route, value: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) });
type BotState = { enabled: boolean; linked: boolean; telegram_username: string | null; notifications_enabled: boolean; bot_username: string | null };

async function setup(page: Page, options: { enabled?: boolean; linked?: boolean; lifetime?: number } = {}) {
  await page.addInitScript(() => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({ user_id: 'tg-user', email: 'tg@example.test', access_token: 'telegram-test-token', refresh_token: 'refresh', token_type: 'bearer', expires_in: 3600, expires_at: Date.now() + 3_600_000 })));
  const state: BotState = { enabled: options.enabled ?? true, linked: options.linked ?? false, telegram_username: null, notifications_enabled: options.linked ?? false, bot_username: 'PostTech_test_bot' };
  const actions: string[] = [];
  let fail = '';
  await page.route('**/api/v1/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/profile') return reply(route, { id: 'tg-user', full_name: 'Тестовый сотрудник', email: 'tg@example.test', role: 'worker', company: 'PostTech', job_title: 'Оператор', department: 'Склад', vacation_days_remaining: 24 });
    if (path.startsWith('/telegram')) {
      const method = route.request().method();
      actions.push(`${method} ${path}`);
      expect(route.request().headers().authorization).toBe('Bearer telegram-test-token');
      if (fail === method) return reply(route, { detail: 'Telegram is temporarily unavailable' }, 503);
      if (method === 'POST') return reply(route, { url: 'https://t.me/PostTech_test_bot?start=one-use-test-secret', expires_at: new Date(Date.now() + (options.lifetime ?? 300_000)).toISOString() });
      if (method === 'DELETE') { state.linked = false; state.telegram_username = null; state.notifications_enabled = false; return reply(route, { linked: false }); }
      if (method === 'PATCH') state.notifications_enabled = route.request().postDataJSON().notifications_enabled;
      return reply(route, state);
    }
    return reply(route, []);
  });
  await page.goto('/settings');
  const section = page.getByRole('region', { name: 'Telegram', exact: true });
  await expect(section.getByRole('button', { name: 'Обновить статус', exact: true })).toBeEnabled();
  return { state, section, actions, setFailure: (method: string) => { fail = method; } };
}

test('Telegram links explicitly, refreshes shared state, toggles notifications and unlinks only after confirmation', async ({ page }, info) => {
  if (info.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 780 });
  const { state, section, actions } = await setup(page);
  expect(actions.length).toBeGreaterThan(0);
  expect(actions.every(action => action === 'GET /telegram/status')).toBe(true);
  await expect(section).toContainText('Telegram получит уведомления');
  await section.getByRole('button', { name: 'Подключить Telegram', exact: true }).click();
  const open = section.getByRole('link', { name: 'Открыть Telegram', exact: true });
  await expect(open).toHaveAttribute('href', 'https://t.me/PostTech_test_bot?start=one-use-test-secret');
  await expect(open).toHaveAttribute('rel', 'noopener noreferrer');
  await expect(section).toContainText('Одноразовая ссылка действует до');
  await section.screenshot({ path: `test-results/telegram-link-${info.project.name}.png` });
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { (window as unknown as { copiedLink: string }).copiedLink = text; } } }));
  await section.getByRole('button', { name: 'Скопировать ссылку', exact: true }).click();
  expect(await page.evaluate(() => (window as unknown as { copiedLink: string }).copiedLink)).toBe('https://t.me/PostTech_test_bot?start=one-use-test-secret');
  const command = section.getByRole('textbox', { name: 'Если кнопка не сработала, отправьте боту эту команду целиком', exact: true });
  await expect(command).toHaveValue('/start one-use-test-secret');
  await expect(command).toHaveAttribute('readonly', '');
  await section.getByRole('button', { name: 'Скопировать команду', exact: true }).click();
  expect(await page.evaluate(() => (window as unknown as { copiedLink: string }).copiedLink)).toBe('/start one-use-test-secret');
  await page.evaluate(() => Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async () => { throw new Error('Clipboard unavailable'); } } }));
  await section.getByRole('button', { name: 'Скопировать команду', exact: true }).click();
  await expect(section.getByRole('alert')).toContainText('Выделите команду в поле и скопируйте вручную');
  await expect(command).toHaveValue('/start one-use-test-secret');
  state.linked = true; state.telegram_username = 'employee_test'; state.notifications_enabled = true;
  await section.getByRole('button', { name: 'Обновить статус', exact: true }).click();
  await expect(section).toContainText('@employee_test');
  await expect(open).toHaveCount(0);
  await expect(command).toHaveCount(0);
  const notifications = section.getByRole('switch', { name: 'Уведомления в Telegram', exact: true });
  await expect(notifications).toBeChecked();
  await notifications.click();
  await expect(notifications).not.toBeChecked();
  expect(state.notifications_enabled).toBe(false);
  await section.getByRole('button', { name: 'Отключить Telegram', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Отключить Telegram?', exact: true });
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  expect(actions).not.toContain('DELETE /telegram/link');
  await section.getByRole('button', { name: 'Отключить Telegram', exact: true }).click();
  await dialog.getByRole('button', { name: 'Отключить Telegram', exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(section.getByRole('button', { name: 'Подключить Telegram', exact: true })).toBeVisible();
  expect(actions.filter(action => action === 'POST /telegram/link')).toHaveLength(1);
  expect(actions.filter(action => action === 'DELETE /telegram/link')).toHaveLength(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});

test('demo never calls Telegram or claims it is connected', async ({ page }) => {
  let telegramCalls = 0;
  await page.route('**/api/v1/telegram/**', route => { telegramCalls++; return reply(route, {}); });
  await page.addInitScript(() => sessionStorage.setItem('posttech.demo-role', 'worker'));
  await page.goto('/settings');
  await expect(page.getByRole('region', { name: 'Telegram', exact: true })).toContainText('Telegram недоступен в демонстрационном режиме');
  await expect(page.getByRole('button', { name: 'Подключить Telegram', exact: true })).toHaveCount(0);
  expect(telegramCalls).toBe(0);
});

test('disabled server explains how to enable the bot without offering a broken link', async ({ page }) => {
  const { section, actions } = await setup(page, { enabled: false });
  await expect(section).toContainText('Подключение Telegram ещё не настроено');
  await expect(section.getByRole('button', { name: 'Подключить Telegram', exact: true })).toHaveCount(0);
  expect(actions.length).toBeGreaterThan(0);
  expect(actions.every(action => action === 'GET /telegram/status')).toBe(true);
});

test('failed mutations preserve account state and show a recoverable error', async ({ page }) => {
  const { section, setFailure } = await setup(page, { linked: true });
  setFailure('PATCH');
  const notifications = section.getByRole('switch', { name: 'Уведомления в Telegram', exact: true });
  await notifications.click();
  await expect(section.getByRole('alert')).toContainText('Telegram временно недоступен');
  await expect(notifications).toBeChecked();
  setFailure('DELETE');
  await section.getByRole('button', { name: 'Отключить Telegram', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Отключить Telegram?', exact: true });
  await dialog.getByRole('button', { name: 'Отключить Telegram', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Telegram временно недоступен');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Отмена', exact: true }).click();
  await expect(section).toContainText('Telegram подключён');
});

test('expired one-use links are removed until the employee requests a new link', async ({ page }) => {
  const { section, actions } = await setup(page, { lifetime: 1500 });
  await section.getByRole('button', { name: 'Подключить Telegram', exact: true }).click();
  await expect(section.getByRole('link', { name: 'Открыть Telegram', exact: true })).toBeVisible();
  await expect(section).toContainText('Срок ссылки истёк');
  await expect(section.getByRole('link', { name: 'Открыть Telegram', exact: true })).toHaveCount(0);
  await expect(section.getByRole('textbox')).toHaveCount(0);
  expect(actions.filter(action => action === 'POST /telegram/link')).toHaveLength(1);
});
