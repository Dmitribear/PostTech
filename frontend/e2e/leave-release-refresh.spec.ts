import { expect, test, type Page } from '@playwright/test';
import type { AppRole, HrRequest, Notification, RequestEvent } from '../src/shared/api/contracts';

const ownerId = '71000000-0000-4000-8000-000000000001';
const reviewerId = '71000000-0000-4000-8000-000000000002';
const requestId = '71000000-0000-4000-8000-000000000101';
const stamp = '2026-10-18T10:00:00Z';
type ReleasedStatus = 'cancelled' | 'rejected';
const statusLabel = { cancelled: 'Отменено', rejected: 'Отклонено' };
const eventTitle = { cancelled: 'Сотрудник отозвал отпуск', rejected: 'Отпуск отклонён' };

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const key = 'leave-refresh-document-loads';
    sessionStorage.setItem(key, String(Number(sessionStorage.getItem(key) || '0') + 1));
  });
});

test.afterEach(async ({ page }) => {
  expect(await page.evaluate(() => sessionStorage.getItem('leave-refresh-document-loads'))).toBe(
    '1',
  );
});

async function mockLeave(page: Page, role: AppRole = 'worker', reviewer = false) {
  const actorId = reviewer ? reviewerId : ownerId;
  const profile = {
    id: actorId,
    employee_code: 'LEAVE-REFRESH',
    full_name: 'Проверка отпуска',
    email: 'leave-refresh@example.test',
    company: 'PostTech',
    job_title: 'Специалист',
    department: 'Логистика',
    manager_id: reviewer ? null : reviewerId,
    hired_at: '2023-01-10',
    vacation_days_remaining: 24,
    role,
    external_source: 'test',
    created_at: stamp,
    updated_at: stamp,
  };
  const record: HrRequest = {
    id: requestId,
    employee_id: ownerId,
    request_type: 'leave',
    status: 'pending',
    start_date: '2030-11-03',
    end_date: '2030-11-06',
    amount: null,
    comment: 'Проверка возврата четырёх дней',
    reviewer_comment: null,
    reviewed_by: null,
    reviewed_at: null,
    created_at: stamp,
    updated_at: stamp,
    approval_route: 'manager',
    approvers: [{ id: reviewerId, full_name: 'Руководитель команды', role: 'manager' }],
    cancelled_at: null,
  };
  const notes: Notification[] = [];
  const history: RequestEvent[] = [
    {
      id: 'created',
      request_id: requestId,
      actor_id: ownerId,
      event_type: 'created',
      from_status: null,
      to_status: 'pending',
      comment: record.comment,
      created_at: stamp,
    },
  ];
  let rejectLateReview = false;
  let accessRevoked = false;
  let reviewAttempts = 0;
  const release = (status: ReleasedStatus) => {
    record.status = status;
    if (status === 'cancelled') record.cancelled_at = stamp;
    else {
      record.reviewed_by = reviewerId;
      record.reviewed_at = stamp;
      record.reviewer_comment = 'Выберите другой период';
    }
    history.push({
      id: status,
      request_id: requestId,
      actor_id: status === 'cancelled' ? ownerId : reviewerId,
      event_type: status,
      from_status: 'pending',
      to_status: status,
      comment: status === 'cancelled' ? 'Отозвана автором' : record.reviewer_comment,
      created_at: stamp,
    });
    notes.unshift({
      id: `note-${status}`,
      employee_id: actorId,
      request_id: requestId,
      notification_type: `request_${status}`,
      title: eventTitle[status],
      body: 'Резерв четырёх дней отпуска освобождён.',
      read_at: null,
      created_at: stamp,
    });
  };
  await page.addInitScript(() =>
    sessionStorage.setItem(
      'jana.hr.session.v1',
      JSON.stringify({
        user_id: 'leave-refresh-user',
        email: 'leave-refresh@example.test',
        access_token: 'test-access-token',
        refresh_token: 'test-refresh-token',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: Date.now() + 3_600_000,
      }),
    ),
  );
  await page.route('**/api/v1/**', async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname.replace('/api/v1', '');
    const respond = (body: unknown, status = 200) => route.fulfill({ status, json: body });
    if (path === '/profile') return respond(profile);
    if (path === '/team')
      return respond([{ ...profile, id: ownerId, role: 'worker', manager_id: reviewerId }]);
    if (path === '/workspace/leave-balance') {
      const pending = record.status === 'pending' ? 4 : 0;
      return respond({
        employee_id: actorId,
        official_days: 24,
        available_days: 24 - pending,
        pending_days: pending,
        approved_unreconciled_days: 0,
        request_days: pending,
        holds: [],
      });
    }
    if (path === '/requests') return respond([record]);
    if (path === `/requests/${requestId}/history`) return respond(history);
    if (path === `/requests/${requestId}/review` && req.method() === 'PATCH') {
      reviewAttempts += 1;
      if (rejectLateReview) {
        release('cancelled');
        return respond({ detail: 'Request is no longer pending' }, 409);
      }
      throw new Error('Unexpected review mutation');
    }
    if (path === `/requests/${requestId}`)
      return accessRevoked ? respond({ detail: 'Forbidden' }, 403) : respond(record);
    if (path === '/notifications') {
      const filtered =
        url.searchParams.get('unread_only') === 'true'
          ? notes.filter((note) => !note.read_at)
          : notes;
      const offset = Number(url.searchParams.get('offset') || 0);
      const limit = Number(url.searchParams.get('limit') || 25);
      return respond(filtered.slice(offset, offset + limit));
    }
    return respond([]);
  });
  return {
    release,
    notes,
    record,
    failLateReview: () => {
      rejectLateReview = true;
    },
    revokeAccess: () => {
      accessRevoked = true;
    },
    reviewAttempts: () => reviewAttempts,
  };
}

for (const role of ['worker', 'manager', 'director', 'hr_admin'] as const) {
  for (const status of ['cancelled', 'rejected'] as const) {
    test(`${role} home releases leave reserve after external ${status} without navigation`, async ({
      page,
    }) => {
      const state = await mockLeave(page, role);
      await page.goto('/');
      await expect(page.locator('.desk-leave-copy')).toContainText('20 дн. доступно');
      await expect(page.locator('.desk-request')).toContainText('Ждёт решения');
      state.release(status);
      await expect(page.locator('.desk-leave-copy')).toContainText('24 дн. доступно');
      await expect(page.locator('.desk-request')).toContainText(statusLabel[status]);
      await expect(page).toHaveURL(/\/$/);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
    });
  }
}

for (const status of ['cancelled', 'rejected'] as const) {
  test(`open request receives external ${status} and history without navigation`, async ({
    page,
  }) => {
    const state = await mockLeave(page);
    await page.goto(`/requests/${requestId}`);
    await expect(page.getByRole('button', { name: 'Отозвать заявку', exact: true })).toBeVisible();
    state.release(status);
    await expect(page.getByRole('region', { name: 'Состояние заявки' })).toContainText(
      status === 'cancelled' ? 'Заявка отозвана' : 'Заявка отклонена',
    );
    await expect(page.locator('.req-history')).toContainText(
      status === 'cancelled' ? 'Заявка отозвана автором' : 'Заявка отклонена',
    );
    await expect(page.getByRole('button', { name: 'Отозвать заявку', exact: true })).toHaveCount(0);
    if (status === 'rejected')
      await expect(page.locator('.req-reviewer-comment')).toContainText('Выберите другой период');
    await expect(page).toHaveURL(new RegExp(`/requests/${requestId}$`));
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });

  test(`recipient sees ${status} notification and external read receipt without navigation`, async ({
    page,
  }) => {
    const state = await mockLeave(
      page,
      status === 'cancelled' ? 'manager' : 'worker',
      status === 'cancelled',
    );
    await page.goto('/notifications');
    await expect(page.getByRole('heading', { name: 'Уведомлений пока нет' })).toBeVisible();
    state.release(status);
    const notification = page
      .locator('.support-notification')
      .filter({ hasText: eventTitle[status] });
    await expect(notification).toBeVisible();
    await expect(notification).toHaveClass(/unread/);
    await expect(page.locator('.notification-button')).toHaveAttribute(
      'aria-label',
      'Уведомления: 1 непрочитанных',
    );
    state.notes[0].read_at = stamp;
    await expect(notification).not.toHaveClass(/unread/);
    await expect(page.locator('.notification-button')).toHaveAttribute(
      'aria-label',
      'Уведомления: 0 непрочитанных',
    );
    await expect(page).toHaveURL(/\/notifications$/);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
  });
}

test('review that races with owner cancellation cannot report false approval', async ({ page }) => {
  const state = await mockLeave(page, 'manager', true);
  state.failLateReview();
  await page.goto(`/requests/${requestId}`);
  await page.getByRole('button', { name: 'Согласовать заявку' }).click();
  const response = page.waitForResponse(
    (res) => res.url().endsWith(`/requests/${requestId}/review`) && res.status() === 409,
  );
  await page.getByRole('button', { name: 'Подтвердить решение' }).click();
  await response;
  await expect(page.getByRole('region', { name: 'Состояние заявки' })).toContainText(
    'Заявка отозвана',
  );
  await expect(page.getByRole('button', { name: 'Согласовать заявку' })).toHaveCount(0);
  await expect(page.locator('.toast').filter({ hasText: 'Заявка согласована' })).toHaveCount(0);
  expect(state.record.status).toBe('cancelled');
  expect(state.reviewAttempts()).toBe(1);
});

test('delegate loses stale decision controls when request access is revoked', async ({ page }) => {
  const state = await mockLeave(page, 'manager', true);
  await page.goto(`/requests/${requestId}`);
  await expect(page.getByRole('button', { name: 'Согласовать заявку' })).toBeVisible();
  state.release('cancelled');
  state.revokeAccess();
  await expect(page.getByRole('button', { name: 'Согласовать заявку' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Отклонить', exact: true })).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'Заявка больше недоступна' })).toBeVisible();
  await expect(
    page.locator('.empty-state').getByRole('link', { name: 'На согласование', exact: true }),
  ).toHaveAttribute('href', '/requests?scope=review');
  await expect(page.getByRole('button', { name: 'Повторить' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Состояние заявки' })).toHaveCount(0);
  expect(state.reviewAttempts()).toBe(0);
});

test('cancelled notification opens a clear closed state for a delegate without request access', async ({
  page,
}) => {
  const state = await mockLeave(page, 'manager', true);
  state.release('cancelled');
  state.revokeAccess();
  await page.goto('/notifications');
  await page.getByRole('link', { name: 'Открыть заявку', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Заявка больше недоступна' })).toBeVisible();
  await expect(
    page.locator('.empty-state').getByRole('link', { name: 'На согласование', exact: true }),
  ).toHaveAttribute('href', '/requests?scope=review');
  await expect(page.getByRole('button', { name: 'Согласовать заявку' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Повторить' })).toHaveCount(0);
});

test('worker without request access returns to personal requests', async ({ page }) => {
  const state = await mockLeave(page);
  state.revokeAccess();
  await page.goto(`/requests/${requestId}`);
  await expect(page.getByRole('heading', { name: 'Заявка больше недоступна' })).toBeVisible();
  await expect(
    page.locator('.empty-state').getByRole('link', { name: 'Мои заявки', exact: true }),
  ).toHaveAttribute('href', '/requests?scope=mine');
  await expect(page.getByRole('button', { name: 'Отозвать заявку', exact: true })).toHaveCount(0);
});
