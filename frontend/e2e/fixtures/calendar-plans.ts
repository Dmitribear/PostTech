import { expect, type Page } from '@playwright/test';
import type {
  AssignedCourse,
  EmployeeProfile,
  HrRequest,
  TeamCourseAssignment,
} from '../../src/shared/api/contracts';

const ownerId = '70000000-0000-4000-8000-000000000001';
const stamp = '2026-10-18T10:00:00Z';

export async function mockPlans(page: Page, role: EmployeeProfile['role']) {
  await page.clock.setFixedTime(new Date('2026-10-18T12:00:00+05:00'));
  await page.addInitScript(() => {
    sessionStorage.setItem(
      'calendar-loads',
      String(Number(sessionStorage.getItem('calendar-loads') || 0) + 1),
    );
    sessionStorage.setItem(
      'jana.hr.session.v1',
      JSON.stringify({
        user_id: 'calendar-user',
        email: 'calendar@example.test',
        access_token: 'test-access',
        refresh_token: 'test-refresh',
        token_type: 'bearer',
        expires_in: 3600,
        expires_at: Date.now() + 3_600_000,
      }),
    );
  });
  const profile = {
    id: ownerId,
    role,
    full_name: 'Проверка календаря',
    email: 'calendar@example.test',
    employee_code: 'CALENDAR',
    company: 'PostTech',
    department: 'Логистика',
    job_title: 'Специалист',
    vacation_days_remaining: 24,
    hired_at: '2023-01-10',
    manager_id: null,
    created_at: stamp,
    updated_at: stamp,
    external_source: 'test',
  };
  const leave = (
    id: string,
    status: HrRequest['status'],
    start_date = '2026-10-30',
    end_date = '2026-11-02',
  ): HrRequest => ({
    id,
    employee_id: ownerId,
    request_type: 'leave',
    status,
    start_date,
    end_date,
    amount: null,
    comment: '',
    reviewer_comment: null,
    reviewed_by: null,
    reviewed_at: null,
    created_at: stamp,
    updated_at: stamp,
  });
  const active = leave('70000000-0000-4000-8000-000000000101', 'approved');
  const pending = leave(
    '70000000-0000-4000-8000-000000000102',
    'pending',
    '2026-10-27',
    '2026-10-28',
  );
  const requests = [
    ...Array.from({ length: 100 }, (_, index) =>
      leave(`old-${index}`, index % 2 ? 'rejected' : 'cancelled'),
    ),
    active,
    pending,
  ];
  const assigned = (
    index: number,
    title: string,
    status: AssignedCourse['status'] = 'in_progress',
  ): AssignedCourse => ({
    id: `assignment-${index}`,
    course_id: `70000000-0000-4000-8000-00000000020${index}`,
    employee_id: ownerId,
    assigned_by: null,
    status,
    progress_percent: 40,
    score_percent: null,
    due_on: '2026-11-01',
    assigned_at: stamp,
    completed_at: null,
    course: {
      id: `70000000-0000-4000-8000-00000000020${index}`,
      title,
      description: '',
      duration_minutes: 15,
    },
  });
  const courses = [
    assigned(1, 'Безопасность персональных данных и правила работы с корпоративными документами'),
    assigned(2, 'Работа в команде'),
    assigned(3, 'Завершённый курс', 'completed'),
  ];
  const pages: number[] = [];
  const teamCourses: TeamCourseAssignment[] = [];
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1', '');
    const respond = (json: unknown) => route.fulfill({ json });
    if (path === '/profile') return respond(profile);
    if (path === '/requests') {
      if (url.searchParams.get('scope') === 'review') return respond([]);
      if (url.searchParams.get('scope') === 'mine')
        expect(url.searchParams.get('employee_id')).toBe(ownerId);
      else expect(url.searchParams.get('scope')).toBe('all');
      const offset = Number(url.searchParams.get('offset') || 0);
      pages.push(offset);
      return respond(requests.slice(offset, offset + Number(url.searchParams.get('limit') || 100)));
    }
    if (path === '/academy/my-courses') return respond(courses);
    if (path === '/academy/team')
      return respond(
        teamCourses.filter(
          (a) =>
            (!url.searchParams.get('employee_id') ||
              a.employee_id === url.searchParams.get('employee_id')) &&
            (!url.searchParams.get('course_id') ||
              a.course_id === url.searchParams.get('course_id')),
        ),
      );
    if (path === '/academy/courses')
      return respond(courses.map((assignment) => ({ ...assignment.course, assignment })));
    const progress = courses.find((a) => path === `/academy/courses/${a.course_id}/progress`);
    if (progress && route.request().method() === 'PATCH') {
      progress.progress_percent = route.request().postDataJSON().progress_percent;
      progress.status = progress.progress_percent === 100 ? 'completed' : 'in_progress';
      return respond(progress);
    }
    const training = [...courses, ...teamCourses].find(
      (assignment) => path === `/academy/courses/${assignment.course?.id}`,
    );
    if (training)
      return respond({
        ...training.course,
        assignment: training.employee_id === ownerId ? training : null,
        quiz: [],
        material_markdown: '# Материал курса',
        active: true,
        created_at: stamp,
      });
    const record = requests.find((item) => path === `/requests/${item.id}`);
    if (record) return respond(record);
    if (path === '/workspace/leave-balance')
      return respond({
        employee_id: ownerId,
        official_days: 24,
        available_days: 18,
        pending_days: 2,
        approved_unreconciled_days: 4,
        holds: [],
      });
    return respond([]);
  });
  return { active, pending, courses, pages, profile, teamCourses };
}
