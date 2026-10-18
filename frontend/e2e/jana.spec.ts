import { expect, test, type Page, type Route } from '@playwright/test';

const employeeId = '40000000-0000-4000-8000-000000000001';
const requestId = '40000000-0000-4000-8000-000000000002';
const sourceId = '40000000-0000-4000-8000-000000000003';
const quote = 'Отпуск оформляется заявкой с датами начала и окончания.';
const source = {
  id: sourceId,
  title: 'Порядок оформления отпуска',
  url: 'https://untrusted.invalid/do-not-follow',
  excerpt: quote,
};
const respond = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

async function livePortal(page: Page, handler: (route: Route, path: string) => Promise<boolean>) {
  await page.addInitScript(() =>
    sessionStorage.setItem(
      'jana.hr.session.v1',
      JSON.stringify({
        user_id: 'test-user',
        email: 'test@example.test',
        access_token: 'test-token',
        refresh_token: 'test-refresh',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: Date.now() + 3600_000,
      }),
    ),
  );
  await page.route('**/api/v1/**', async (route) => {
    expect(route.request().headers().authorization).toBe('Bearer test-token');
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (await handler(route, path)) return;
    if (path.startsWith('/workspace/fulfillment/'))
      return respond(route, {
        status: 'awaiting_hr',
        note: '',
        can_send: false,
        deliveries: [],
        events: [],
      });
    if (path === '/profile')
      return respond(route, {
        id: employeeId,
        employee_code: 'TEST-01',
        full_name: 'Тестовый Сотрудник',
        email: 'test@example.test',
        company: 'PostTech',
        job_title: 'Оператор',
        department: 'Хаб',
        manager_id: null,
        hired_at: '2023-01-10',
        vacation_days_remaining: 24,
        role: 'worker',
        external_source: 'test',
        created_at: '2026-01-01T10:00:00Z',
        updated_at: '2026-10-01T10:00:00Z',
      });
    return respond(route, []);
  });
}

test('live Jana opens authenticated sources, shows refusals and retains questions on model failure', async ({
  page,
}, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let sourceMissing = false;
  let askCount = 0;
  await livePortal(page, async (route, path) => {
    if (path === '/ai/ask') {
      askCount++;
      const question = route.request().postDataJSON().question;
      if (question === 'Недоступная модель')
        await respond(route, { detail: 'Jana AI is temporarily unavailable' }, 503);
      else if (question === 'Расскажи про погоду')
        await respond(route, {
          answer: 'В базе нет подтверждённой информации.',
          sources: [],
          grounded: false,
          escalation_suggested: true,
          mode: 'refusal',
        });
      else
        await respond(route, {
          answer: quote,
          sources: [source],
          grounded: true,
          escalation_suggested: false,
          mode: 'excerpts',
        });
      return true;
    }
    if (path === `/ai/sources/${sourceId}`) {
      await respond(
        route,
        sourceMissing
          ? { detail: 'Source not found' }
          : {
              id: sourceId,
              title: source.title,
              content: `${quote}\nЭто полный проверяемый материал.\n<script>alert('not executed')</script>`,
              source_title: 'Тестовый HR-документ',
              source_url: null,
            },
        sourceMissing ? 404 : 200,
      );
      return true;
    }
    return false;
  });
  await page.goto('/jana');
  await page.getByRole('button', { name: 'Как оформить отпуск?', exact: true }).click();
  await expect(page.locator('.support-answer-text')).toHaveText(quote);
  await page.getByRole('button', { name: source.title, exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Это полный проверяемый материал.');
  await expect(page.getByRole('dialog')).toContainText('<script>');
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1),
  ).toBe(false);
  await page.screenshot({
    path: `test-results/jana-source-${testInfo.project.name}.png`,
    fullPage: true,
  });
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  sourceMissing = true;
  await page.getByRole('button', { name: source.title, exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('больше не опубликован');
  sourceMissing = false;
  await page.getByRole('button', { name: 'Повторить', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Это полный проверяемый материал.');
  await page.getByRole('button', { name: 'Закрыть', exact: true }).click();
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Расскажи про погоду');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  await expect(page.locator('.support-message.jana').last()).toContainText(
    'нет подтверждённой информации',
  );
  await expect(
    page.locator('.support-message.jana').last().locator('.support-citation'),
  ).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Недоступная модель');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  await expect(page.getByRole('alert')).toContainText('Jana сейчас недоступна');
  await expect(page.getByRole('textbox', { name: 'Ваш вопрос Jana' })).toHaveValue(
    'Недоступная модель',
  );
  await expect(page.locator('.support-message.jana')).toHaveCount(2);
  expect(askCount).toBe(3);
  expect(errors).toEqual([]);
});

test('Jana offers direct leave and learning buttons for paraphrases and compound questions', async ({
  page,
}) => {
  const leave = { id: 'leave_new', label: 'Оформить отпуск', href: '/calendar?select=1' };
  const course = { id: 'academy', label: 'Обучение', href: '/academy' };
  await livePortal(page, async (route, path) => {
    if (path !== '/ai/ask') return false;
    const question = route.request().postDataJSON().question;
    const actions =
      question === 'Хочу взять несколько дней отдыха, куда нажать?'
        ? [leave]
        : question === 'Мне назначили учебный материал, где его открыть?'
          ? [course]
          : [leave, course];
    await respond(route, {
      answer: 'Откройте нужный раздел портала.',
      sources: [source],
      grounded: true,
      escalation_suggested: false,
      mode: 'generated',
      actions,
    });
    return true;
  });
  await page.goto('/jana');
  async function ask(question: string) {
    await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill(question);
    await page.getByRole('button', { name: 'Отправить вопрос' }).click();
    await expect(page.getByRole('textbox', { name: 'Ваш вопрос Jana' })).toBeEnabled();
    return page.locator('.support-message.jana').last();
  }
  const leaveAnswer = await ask('Хочу взять несколько дней отдыха, куда нажать?');
  await expect(leaveAnswer.locator('.support-answer-action')).toHaveCount(1);
  await expect(leaveAnswer.getByRole('link', { name: 'Оформить отпуск' })).toHaveAttribute(
    'href',
    '/calendar?select=1',
  );
  const courseAnswer = await ask('Мне назначили учебный материал, где его открыть?');
  await expect(courseAnswer.getByRole('link', { name: 'Обучение', exact: true })).toHaveAttribute(
    'href',
    '/academy',
  );
  const combinedAnswer = await ask('Хочу оформить отдых и пройти назначенный курс');
  await expect(combinedAnswer.locator('.support-answer-action')).toHaveCount(2);
  for (const link of await combinedAnswer.locator('.support-answer-action').all()) {
    const box = await link.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    expect(box!.height).toBeGreaterThanOrEqual(44);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(
    false,
  );
  await combinedAnswer.getByRole('link', { name: 'Обучение', exact: true }).click();
  await expect(page).toHaveURL(/\/academy$/);
});

test('Jana hides off-topic escalation and rejects unsafe or unauthorized action links', async ({
  page,
}) => {
  await livePortal(page, async (route, path) => {
    if (path !== '/ai/ask') return false;
    const offTopic = route.request().postDataJSON().question === 'Напиши рецепт пиццы';
    await respond(route, {
      answer: offTopic
        ? 'Я помогаю только по рабочим вопросам PostTech.'
        : 'Откройте назначенное обучение.',
      sources: offTopic ? [] : [source],
      grounded: !offTopic,
      escalation_suggested: false,
      mode: offTopic ? 'refusal' : 'generated',
      actions: [
        { id: 'leave_new', label: 'Оформить отпуск', href: 'https://untrusted.invalid' },
        { id: 'requests_review', label: 'Одобрить заявки', href: '/requests?scope=review' },
        { id: 'unknown', label: 'Открыть профиль', href: '/profile' },
        { id: 'academy', label: 'Введите пароль', href: '/academy' },
        { id: 'academy', label: 'Дубликат', href: '/academy' },
      ],
    });
    return true;
  });
  await page.goto('/jana');
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Напиши рецепт пиццы');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  const refusal = page.locator('.support-message.jana').last();
  await expect(refusal).toContainText('только по рабочим вопросам');
  await expect(refusal.locator('.support-answer-action')).toHaveCount(0);
  await expect(refusal.getByRole('button', { name: 'Передать вопрос в HR' })).toHaveCount(0);
  await page.getByRole('textbox', { name: 'Ваш вопрос Jana' }).fill('Где найти обучение?');
  await page.getByRole('button', { name: 'Отправить вопрос' }).click();
  const answer = page.locator('.support-message.jana').last();
  await expect(answer).toContainText('назначенное обучение');
  await expect(answer.locator('.support-answer-action')).toHaveCount(1);
  await expect(answer.getByRole('link', { name: 'Обучение', exact: true })).toHaveAttribute(
    'href',
    '/academy',
  );
  await expect(answer).not.toContainText('Введите пароль');
  await expect(answer.locator('a[href^="https://"]')).toHaveCount(0);
});

test('approved leave downloads authenticated ICS, and changed status remains an error', async ({
  page,
}) => {
  let status = 'approved';
  let rejectExport = false;
  const ics =
    'BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:20261231\r\nDTEND;VALUE=DATE:20270101\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n';
  await livePortal(page, async (route, path) => {
    if (path === `/requests/${requestId}`) {
      await respond(route, {
        id: requestId,
        employee_id: employeeId,
        request_type: 'leave',
        status,
        start_date: '2026-12-31',
        end_date: '2026-12-31',
        comment: null,
        amount: null,
        created_at: '2026-10-16T10:00:00Z',
        updated_at: '2026-10-16T10:00:00Z',
        reviewer_comment: null,
        reviewed_by: null,
        reviewed_at: null,
      });
      return true;
    }
    if (path.endsWith('/calendar.ics')) {
      if (rejectExport)
        await respond(route, { detail: 'Calendar export requires an approved leave request' }, 409);
      else await route.fulfill({ contentType: 'text/calendar; charset=utf-8', body: ics });
      return true;
    }
    return false;
  });
  await page.goto(`/requests/${requestId}`);
  const downloadReady = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Скачать отпуск (.ics)' }).click();
  const download = await downloadReady;
  expect(download.suggestedFilename()).toBe(`leave-${requestId}.ics`);
  const stream = await download.createReadStream();
  let contents = '';
  for await (const chunk of stream!) contents += chunk.toString();
  expect(contents).toBe(ics);
  await expect(page.locator('#main-content')).toContainText('Импорт выполняется вручную');
  rejectExport = true;
  await page.getByRole('button', { name: 'Скачать отпуск (.ics)' }).click();
  await expect(page.getByRole('alert')).toContainText('только для одобренного отпуска');
  status = 'pending';
  await page.reload();
  await expect(page.getByRole('heading', { name: 'Заявка на отпуск', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Скачать отпуск (.ics)' })).toHaveCount(0);
});
