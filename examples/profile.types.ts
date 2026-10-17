// GET /api/v1/profile. UUIDs and ISO dates are serialized as strings.
// See docs/profile-api.md for access rules, empty states and example JSON.
export type ProfileRole = 'worker' | 'manager' | 'director' | 'hr_admin';
export type CourseStatus = 'not_started' | 'in_progress' | 'completed';

export interface ProfileManager {
  id: string;
  full_name: string;
}

export interface ProfileCourse {
  id: string;
  title: string;
  description: string;
  duration_minutes: number;
}

export interface ProfileCourseAssignment {
  id: string;
  course_id: string;
  employee_id: string;
  status: CourseStatus;
  progress_percent: number;
  score_percent: number | null;
  assigned_by: string | null;
  assigned_at: string;
  completed_at: string | null;
  course: ProfileCourse | null;
}

export interface ProfileNotification {
  id: string;
  employee_id: string;
  request_id: string | null;
  notification_type: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

export interface EmployeeProfile {
  id: string;
  employee_code: string;
  full_name: string;
  email: string;
  company: string;
  job_title: string;
  department: string;
  manager_id: string | null;
  hired_at: string;
  vacation_days_remaining: number;
  role: ProfileRole;
  external_source: string;
  created_at: string;
  updated_at: string;
  manager: ProfileManager | null;
  assigned_courses: ProfileCourseAssignment[];
  notifications: ProfileNotification[];
}
