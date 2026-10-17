import { describe, expect, it } from 'vitest';
import { homeCourses, nextCourse } from './home-learning';
import type { AssignedCourse, Course } from './types';

const course = (id: string, status: string, due_on: string | null = null) => ({id, assignment: {status, due_on}} as Course);
describe('home learning shortcut', () => {
  it('prioritizes the earliest deadline, then an unfinished course', () => {
    const courses = [course('complete', 'completed', '2026-01-01'), course('started', 'in_progress'), course('due', 'not_started', '2026-10-20')];
    expect(nextCourse(courses)?.id).toBe('due');
    expect(nextCourse(courses.slice(0, 2))?.id).toBe('started');
    expect(nextCourse([courses[0]])).toBeUndefined();
    expect(courses[0].id).toBe('complete');
  });
  it('includes assigned versions independently of the published catalog', () => {
    const assignments = [{course_id: 'archived', course: {id:'archived',title:'Version 1'}, status:'in_progress'}, {course_id:'missing',course:null}] as AssignedCourse[];
    expect(homeCourses(assignments)).toHaveLength(1);
    expect(nextCourse(homeCourses(assignments))?.id).toBe('archived');
  });
});
