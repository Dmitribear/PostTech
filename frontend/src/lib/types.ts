export type AppRole = 'worker' | 'manager' | 'hr_admin';
export type RequestType = 'leave' | 'advance';
export type RequestStatus = 'pending' | 'approved' | 'rejected' | 'cancelled';
export type CourseStatus = 'not_started' | 'in_progress' | 'completed';

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
  role: AppRole;
  external_source: string;
  created_at: string;
  updated_at: string;
}

export interface AuthResponse {
  user_id: string;
  email: string;
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface AuthSession extends AuthResponse {
  /** Unix timestamp in milliseconds; only kept in this tab's sessionStorage. */
  expires_at: number;
}

export interface RegistrationResponse {
  user_id: string | null;
  email: string;
  email_confirmation_required: boolean;
  message: string;
  access_token?: string;
  refresh_token?: string;
  token_type?: string;
  expires_in?: number;
}

export interface HrRequest {
  id: string;
  employee_id: string;
  request_type: RequestType;
  status: RequestStatus;
  start_date: string | null;
  end_date: string | null;
  amount: number | null;
  comment: string;
  reviewer_comment: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export type RequestCreate = {
  request_type: 'leave';
  start_date: string;
  end_date: string;
  amount?: never;
  comment?: string;
} | {
  request_type: 'advance';
  amount: number;
  start_date?: never;
  end_date?: never;
  comment?: string;
};

export interface RequestReview {
  status: 'approved' | 'rejected';
  reviewer_comment?: string | null;
}

export interface RequestFilters {
  employee_id?: string;
  status?: RequestStatus;
  request_type?: RequestType;
  limit?: number;
  offset?: number;
}

export interface RequestEvent {
  id: string;
  request_id: string;
  actor_id: string | null;
  event_type: 'created' | 'approved' | 'rejected';
  from_status: RequestStatus | null;
  to_status: RequestStatus;
  comment: string;
  created_at: string;
}

export interface Notification {
  id: string;
  employee_id: string;
  request_id: string | null;
  notification_type: string;
  title: string;
  body: string;
  read_at: string | null;
  created_at: string;
}

export interface NotificationFilters {
  request_id?: string;
  unread_only?: boolean;
  limit?: number;
  offset?: number;
}

export interface CourseAssignmentSummary {
  course_id: string;
  status: CourseStatus;
  progress_percent: number;
  score_percent: number | null;
  assigned_at: string;
  completed_at: string | null;
}

export interface CourseAssignment extends CourseAssignmentSummary {
  id: string;
  employee_id: string;
  assigned_by: string | null;
}

export interface CourseSummary {
  id: string;
  title: string;
  description: string;
  duration_minutes: number;
}

export interface Course extends CourseSummary {
  assignment: CourseAssignmentSummary | null;
}

export interface QuizQuestion {
  id: string;
  prompt: string;
  options: string[];
}

export interface CourseDetail extends CourseSummary {
  material_markdown: string;
  quiz: QuizQuestion[];
  active: boolean;
  created_at: string;
  assignment: CourseAssignment | null;
}

export interface AssignedCourse extends CourseAssignment {
  course: CourseSummary | null;
}

export interface JanaAnswer {
  answer: string;
  sources: { title: string; url: string | null }[];
  grounded: boolean;
  escalation_suggested: boolean;
}

/** Shared contract: live HTTP and explicitly selected demonstration mode. */
export interface HrApi {
  readonly mode: 'live' | 'demo';
  getProfile(): Promise<EmployeeProfile>;
  getEmployee(id: string): Promise<EmployeeProfile>;
  getTeam(): Promise<EmployeeProfile[]>;
  getRequests(filters?: RequestFilters): Promise<HrRequest[]>;
  createRequest(payload: RequestCreate, idempotencyKey?: string): Promise<HrRequest>;
  getRequest(id: string): Promise<HrRequest>;
  getRequestHistory(id: string): Promise<RequestEvent[]>;
  reviewRequest(id: string, payload: RequestReview): Promise<HrRequest>;
  getNotifications(filters?: NotificationFilters): Promise<Notification[]>;
  markNotificationRead(id: string): Promise<Notification>;
  getCourses(): Promise<Course[]>;
  getMyCourses(): Promise<AssignedCourse[]>;
  getCourse(id: string): Promise<CourseDetail>;
  assignCourse(employeeId: string, courseId: string): Promise<CourseAssignment>;
  updateCourseProgress(id: string, percent: number): Promise<CourseAssignment>;
  completeCourse(id: string, answers: Record<string, number>): Promise<CourseAssignment>;
  askJana(question: string): Promise<JanaAnswer>;
}
