import { describe, expect, it } from 'vitest';
import type { Course, HrRequest } from '@/shared/api/contracts';
import { eventsForDay } from './calendar-events';

const leave = (
  id: string,
  status: HrRequest['status'] = 'approved',
  start_date = '2026-10-30',
  end_date = '2026-11-02',
) => ({ id, status, start_date, end_date, request_type: 'leave' }) as HrRequest;
const course = (id: string, status = 'in_progress', due_on: string | null = '2026-11-01') =>
  ({ id, assignment: { status, due_on } }) as Course;

describe('calendar plans', () => {
  it('includes every day of a leave across months, including its boundaries', () => {
    const requests = [leave('leave')];
    for (const day of ['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-02']) {
      expect(eventsForDay(day, requests, []).leaves).toHaveLength(1);
    }
    for (const day of ['2026-10-29', '2026-11-03'])
      expect(eventsForDay(day, requests, []).leaves).toEqual([]);
  });
  it('keeps pending leave but drops rejected and cancelled requests and advances', () => {
    const requests = [
      leave('approved'),
      leave('pending', 'pending'),
      leave('rejected', 'rejected'),
      leave('cancelled', 'cancelled'),
      { ...leave('advance'), request_type: 'advance' } as HrRequest,
    ];
    expect(eventsForDay('2026-11-01', requests, []).leaves.map((item) => item.id)).toEqual([
      'approved',
      'pending',
    ]);
    requests[0].status = 'cancelled';
    expect(eventsForDay('2026-11-01', requests, []).leaves.map((item) => item.id)).toEqual([
      'pending',
    ]);
  });
  it('combines leave and several unfinished course deadlines without limiting to the latest three requests', () => {
    const requests = Array.from({ length: 5 }, (_, index) =>
      leave(
        String(index),
        'approved',
        index === 4 ? '2026-10-30' : '2026-12-01',
        index === 4 ? '2026-11-02' : '2026-12-05',
      ),
    );
    const result = eventsForDay('2026-11-01', requests, [
      course('a'),
      course('b', 'not_started'),
      course('done', 'completed'),
      course('no-due', 'not_started', null),
    ]);
    expect(result.leaves.map((item) => item.id)).toEqual(['4']);
    expect(result.courses.map((item) => item.id)).toEqual(['a', 'b']);
  });
  it('moves deadlines and removes completed courses on updated data', () => {
    const courses = [course('training')];
    courses[0].assignment!.due_on = '2026-11-02';
    expect(eventsForDay('2026-11-01', [], courses).courses).toEqual([]);
    expect(eventsForDay('2026-11-02', [], courses).courses).toHaveLength(1);
    courses[0].assignment!.status = 'completed';
    expect(eventsForDay('2026-11-02', [], courses).courses).toEqual([]);
  });
});
