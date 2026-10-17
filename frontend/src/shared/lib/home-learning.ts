import type { AssignedCourse, Course } from '@/shared/api/contracts';

// Assigned archived versions remain available until the employee completes them.
export function homeCourses(assignments: AssignedCourse[]): Course[] {
  return assignments.flatMap((assignment) =>
    assignment.course ? [{ ...assignment.course, assignment }] : [],
  );
}

export function nextCourse(courses: Course[]): Course | undefined {
  return courses
    .filter((course) => course.assignment && course.assignment.status !== 'completed')
    .sort(
      (a, b) =>
        (a.assignment!.due_on || '9999').localeCompare(b.assignment!.due_on || '9999') ||
        Number(b.assignment!.status === 'in_progress') -
          Number(a.assignment!.status === 'in_progress') ||
        a.id.localeCompare(b.id),
    )[0];
}
