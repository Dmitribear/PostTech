import type { Course, HrRequest } from '@/shared/api/contracts';

export function scheduledLeaves(requests: HrRequest[]) {
  return requests.filter(
    (request) =>
      request.request_type === 'leave' &&
      (request.status === 'pending' || request.status === 'approved') &&
      request.start_date &&
      request.end_date,
  );
}

export function scheduledCourses<T extends Course>(courses: T[]) {
  return courses.filter(
    (course) =>
      course.assignment && course.assignment.status !== 'completed' && course.assignment.due_on,
  );
}

export function eventsForDay<T extends Course>(day: string, requests: HrRequest[], courses: T[]) {
  return {
    leaves: scheduledLeaves(requests).filter(
      (request) => request.start_date! <= day && day <= request.end_date!,
    ),
    courses: scheduledCourses(courses).filter((course) => course.assignment!.due_on === day),
  };
}
