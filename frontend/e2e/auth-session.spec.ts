import { expect, test, type BrowserContext, type Page } from '@playwright/test';

const sessionKey = 'jana.hr.session.v1';
const firstEmail = 'first@example.test';
const secondEmail = 'second@example.test';

function auth(email = firstEmail) {
  return {
    user_id: email,
    email,
    access_token: `access:${email}`,
    refresh_token: `refresh:${email}`,
    token_type: 'bearer',
    expires_in: 3600,
  };
}

async function mockApi(context: BrowserContext, refresh?: () => Promise<void>) {
  await context.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1', '');
    const respond = (value: unknown) => route.fulfill({ json: value });
    if (path === '/auth/login') return respond(auth(request.postDataJSON().email));
    if (path === '/auth/refresh') {
      await refresh?.();
      return respond({ ...auth(), access_token: 'rotated-access', refresh_token: 'rotated-refresh' });
    }
    const email = request.headers().authorization?.includes(secondEmail) ? secondEmail : firstEmail;
    if (path === '/profile') {
      return respond({
        id: email,
        employee_code: 'TEST',
        full_name: email === firstEmail ? 'Первый Сотрудник' : 'Второй Сотрудник',
        email,
        role: 'worker',
        company: 'PostTech',
        job_title: 'Оператор',
        department: 'Хаб',
        hired_at: '2023-01-10',
        manager_id: null,
        vacation_days_remaining: 24,
        external_source: 'test',
        created_at: '2026-01-01T10:00:00Z',
        updated_at: '2026-01-01T10:00:00Z',
      });
    }
    if (path === '/workspace/leave-balance') {
      return respond({
        employee_id: email,
        official_days: 24,
        pending_days: 0,
        approved_unreconciled_days: 0,
        available_days: 24,
        request_days: 0,
        holds: [],
      });
    }
    return respond([]);
  });
}

async function login(page: Page, email = firstEmail) {
  await page.getByLabel('Рабочая почта', { exact: true }).fill(email);
  await page.locator('input[autocomplete="current-password"]').fill('TestPassword123!');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.locator('#main-content')).toBeVisible();
}

async function logout(page: Page) {
  await page.getByLabel('Меню профиля', { exact: true }).click();
  await page.locator('.account-popover').getByRole('button', { name: 'Выйти', exact: true }).click();
  await expect(page.locator('input[autocomplete="current-password"]')).toBeVisible();
}

test('login is shared with existing and new tabs; logout and account changes synchronize', async ({
  context,
  page,
}) => {
  await mockApi(context);
  await page.goto('/profile');
  const waiting = await context.newPage();
  await waiting.goto('/profile');
  await expect(waiting.locator('input[autocomplete="current-password"]')).toBeVisible();
  await login(page);
  await expect(waiting.locator('.support-profile-person')).toContainText('Первый Сотрудник');

  // Opening the copied URL has no sessionStorage inherited from an opener.
  const copied = await context.newPage();
  await copied.goto(page.url());
  await expect(copied.locator('.support-profile-person')).toContainText('Первый Сотрудник');
  expect(await copied.evaluate((key) => sessionStorage.getItem(key), sessionKey)).toBeNull();
  await copied.reload();
  await expect(copied.locator('.support-profile-person')).toContainText('Первый Сотрудник');

  await logout(page);
  for (const tab of [waiting, copied]) {
    await expect(tab.locator('input[autocomplete="current-password"]')).toBeVisible();
    await expect(tab.locator('#main-content')).toHaveCount(0);
  }
  await login(page, secondEmail);
  for (const tab of [waiting, copied]) {
    await expect(tab.locator('.support-profile-person')).toContainText('Второй Сотрудник');
    await expect(tab.locator('#main-content')).not.toContainText('Первый Сотрудник');
  }
});

test('two tabs starting with an expired token perform one shared refresh', async ({ context, page }) => {
  let refreshes = 0;
  await mockApi(context, async () => {
    refreshes += 1;
    await new Promise((resolve) => setTimeout(resolve, 250));
  });
  await context.addInitScript(({ key, initial }) => {
    if (!localStorage.getItem(key)) {
      localStorage.setItem(key, JSON.stringify({ ...initial, expires_at: Date.now() - 1000 }));
    }
  }, { key: sessionKey, initial: auth() });
  const second = await context.newPage();
  await Promise.all([page.goto('/profile'), second.goto('/profile')]);
  for (const tab of [page, second]) {
    await expect(tab.locator('.support-profile-person')).toContainText('Первый Сотрудник');
  }
  expect(refreshes).toBe(1);
});
