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

test('external demo learning keeps self enrollment, progress and one completion notification', async () => {
  const store = storage();
  const worker = createSharedDemoApi('worker', store);
  const manager = createSharedDemoApi('manager', store);
  const course = (await worker.getCourses()).find((c) => c.course_type === 'external')!;
  const first = await worker.enrollExternalCourse(course.id);
  expect((await worker.enrollExternalCourse(course.id)).id).toBe(first.id);
  await worker.updateCourseProgress(course.id, 65);
  const team = await manager.getTeamCourses({ course_id: course.id });
  expect(team[0].progress_percent).toBe(65);
  expect(team[0].course?.provider).toBe('Яндекс Практикум');
  const completed = await worker.updateCourseProgress(course.id, 100);
  expect(completed.status).toBe('completed');
  expect(completed.score_percent).toBeNull();
  await worker.updateCourseProgress(course.id, 100);
  expect((await manager.getNotifications()).filter((n) => n.course_id === course.id)).toHaveLength(
    1,
  );
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

test('personal courses persist across sessions and remain outside the public catalog', async () => {
  const store = storage();
  const worker = createSharedDemoApi('worker', store);
  const manager = createSharedDemoApi('manager', store);
  const hr = createSharedDemoApi('hr_admin', store);
  const input = {
    id: crypto.randomUUID(),
    title: 'Личный курс Excel',
    provider: 'Практикум',
    external_url: 'https://example.com/excel',
    due_on: '2027-01-01',
    progress_percent: 35,
  };
  const created = await worker.createPersonalCourse(input);
  expect((await worker.createPersonalCourse(input)).id).toBe(created.id);
  const reopened = createSharedDemoApi('worker', store);
  expect((await reopened.getMyCourses()).find((a) => a.course_id === input.id)?.due_on).toBe(
    input.due_on,
  );
  for (const api of [worker, manager, hr])
    expect((await api.getCourses()).some((c) => c.id === input.id)).toBe(false);
  for (const api of [manager, hr]) {
    expect(
      (await api.getTeamCourses()).find((a) => a.course_id === input.id)?.progress_percent,
    ).toBe(35);
    expect((await api.getCourse(input.id)).external_url).toBe(input.external_url);
  }
  await expect(manager.enrollExternalCourse(input.id)).rejects.toMatchObject({ status: 403 });
  await reopened.updateCourseProgress(input.id, 70);
  expect(
    (await manager.getTeamCourses()).find((a) => a.course_id === input.id)?.progress_percent,
  ).toBe(70);
  await expect(
    worker.createPersonalCourse({ ...input, title: 'Другая версия' }),
  ).rejects.toMatchObject({ status: 409 });
});
