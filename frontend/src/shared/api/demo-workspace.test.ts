import { expect, test } from 'vitest';
import { createSharedDemoApi } from './demo-workspace';

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}
const leave = { request_type: 'leave' as const, start_date: '2090-06-01', end_date: '2090-06-03' };
type Balance = { available_days: number; pending_days: number; approved_unreconciled_days: number };

test.each(['approved', 'rejected', 'cancelled'] as const)(
  'shared demo routes a leave request and synchronizes %s',
  async (decision) => {
    const store = storage();
    const worker = createSharedDemoApi('worker', store);
    const manager = createSharedDemoApi('manager', store);
    const before = await worker.workspace<Balance>('/leave-balance');
    const created = await worker.createRequest(leave, 'one-submission');
    const queue = await manager.getRequests({ scope: 'review', status: 'pending' });
    expect(queue.some((r) => r.id === created.id)).toBe(true);
    expect(await manager.getNotifications({ request_id: created.id })).toHaveLength(1);
    expect((await worker.workspace<Balance>('/leave-balance')).available_days).toBe(
      before.available_days - 3,
    );
    if (decision === 'cancelled') await worker.cancelRequest(created.id);
    else
      await manager.reviewRequest(created.id, { status: decision, reviewer_comment: 'Проверка' });
    const reopened = createSharedDemoApi('worker', store);
    expect((await reopened.getRequest(created.id)).status).toBe(decision);
    expect(await reopened.getRequestHistory(created.id)).toHaveLength(2);
    expect(await reopened.getNotifications({ request_id: created.id })).toHaveLength(2);
    expect((await reopened.workspace<Balance>('/leave-balance')).available_days).toBe(
      before.available_days - (decision === 'approved' ? 3 : 0),
    );
    expect(
      (await manager.getRequests({ scope: 'review', status: 'pending' })).some(
        (r) => r.id === created.id,
      ),
    ).toBe(false);
    const same = await reopened.createRequest(leave, 'one-submission');
    expect(same.id).toBe(created.id);
  },
);

test('simultaneous demo tabs preserve both writes and isolate submission keys by actor', async () => {
  const store = storage();
  const worker = createSharedDemoApi('worker', store);
  const manager = createSharedDemoApi('manager', store);
  const [one, two] = await Promise.all([
    worker.createRequest({ request_type: 'advance', amount: 100 }, 'same-key'),
    manager.createRequest({ request_type: 'advance', amount: 200 }, 'same-key'),
  ]);
  expect(one.id).not.toBe(two.id);
  const hr = createSharedDemoApi('hr_admin', store);
  expect((await hr.getRequests()).map((r) => r.id)).toEqual(
    expect.arrayContaining([one.id, two.id]),
  );
  await expect(worker.getRequest(two.id)).rejects.toMatchObject({ status: 403 });
  await expect(manager.reviewRequest(two.id, { status: 'approved' })).rejects.toMatchObject({
    status: 403,
  });
  expect(await hr.getNotifications({ request_id: two.id })).toHaveLength(1);
});

test('course progress survives role changes and is visible to the manager', async () => {
  const store = storage();
  const worker = createSharedDemoApi('worker', store);
  const profile = await worker.getProfile();
  const course = (await worker.getCourses()).find((c) => c.assignment?.status === 'in_progress')!;
  await worker.updateCourseProgress(course.id, 80);
  const manager = createSharedDemoApi('manager', store);
  const assignments = await manager.getTeamCourses({
    employee_id: profile.id,
    course_id: course.id,
  });
  expect(assignments[0].progress_percent).toBe(80);
});

test('failed storage writes cannot report a successful submission', async () => {
  const store = storage();
  const worker = createSharedDemoApi('worker', store);
  await worker.getProfile();
  const fail = createSharedDemoApi('worker', {
    ...store,
    setItem() {
      throw new Error('quota');
    },
  });
  await expect(fail.createRequest({ request_type: 'advance', amount: 17 })).rejects.toMatchObject({
    status: 503,
  });
  expect((await worker.getRequests()).some((r) => r.amount === 17)).toBe(false);
});

test('unread state persists in another role instance', async () => {
  const store = storage();
  const worker = createSharedDemoApi('worker', store);
  const manager = createSharedDemoApi('manager', store);
  const request = await worker.createRequest(leave);
  const [notification] = await manager.getNotifications({ request_id: request.id });
  await manager.markNotificationRead(notification.id);
  expect(
    await createSharedDemoApi('manager', store).getNotifications({
      request_id: request.id,
      unread_only: true,
    }),
  ).toHaveLength(0);
});
