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
  manager_name?: string | null;
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

export interface InvitationPreview {
  email: string;
  role: AppRole;
  department: string;
  expires_at: string;
}

export interface RegistrationInput {
  invitation_code: string;
  first_name: string;
  last_name: string;
  password: string;
}

export interface RegistrationVerification {
  invitation_code: string;
  token: string;
}

export interface InvitationCompletion {
  invitation_code: string;
  email: string;
  password: string;
  first_name?: string;
  last_name?: string;
}

export interface InvitationInput {
  email: string;
  employee_code: string;
  company: string;
  job_title: string;
  department: string;
  hired_at: string;
  manager_id: string | null;
  role: AppRole;
  vacation_days_remaining: number;
  expires_in_hours: number;
}

export interface IssuedInvitation extends InvitationPreview {
  id: string;
  invitation_code: string;
  email_status?: 'not_configured' | 'accepted' | 'failed' | 'unknown' | 'not_sent' | 'sending';
}

export interface InvitationRecord extends InvitationPreview {
  email_status?: IssuedInvitation['email_status'];
  email_attempted_at?: string | null;
  id: string;
  employee_code: string;
  created_at: string;
  consumed_at: string | null;
  revoked_at: string | null;
}

export interface HrRequest {
  fulfillment?: {status: 'awaiting_hr'|'processing'|'completed'} | null;
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
  approval_route?: 'manager' | 'hr' | 'unassigned';
  approvers?: Approver[];
  cancelled_at?: string | null;
  can_review?: boolean;
}

export interface Approver { id: string; full_name: string; role: 'manager' | 'hr_admin' }
export interface RequestRouting {
  can_submit: boolean;
  route: 'manager' | 'hr' | 'unassigned';
  approvers: Approver[];
  message: string | null;
  today: string;
  policy: string;
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
  scope?: 'all' | 'mine' | 'review';
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
  delegation_id?: string | null;
  event_type: 'created' | 'approved' | 'rejected' | 'cancelled';
  from_status: RequestStatus | null;
  to_status: RequestStatus;
  comment: string;
  created_at: string;
}

export interface Notification {
  id: string;
  employee_id: string;
  request_id: string | null;
  course_id?: string | null;
  ticket_id?: string | null;
  notification_type: string;
  title: string;
  body: string;
  original_body?: string | null;
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
  completed_lesson_ids?: string[];
  course_id: string;
  status: CourseStatus;
  progress_percent: number;
  score_percent: number | null;
  due_on?: string | null;
  assigned_at: string;
  completed_at: string | null;
  attempt_count?: number;
  material_completed_at?: string | null;
  last_attempt_at?: string | null;
}

export interface CourseAssignment extends CourseAssignmentSummary {
  id: string;
  employee_id: string;
  assigned_by: string | null;
}

export interface CourseSummary {
  content_language?: string;
  id: string;
  title: string;
  description: string;
  duration_minutes: number;
  category?: string;
  audience?: string;
  passing_score?: number;
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
  lessons?: {id: string; title: string; material_markdown: string}[];
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
  mode?: 'generated' | 'excerpt' | 'refusal' | 'summary';
  report?: {as_of:string;sections:{title:string;count:number;href:string;items:{label:string;href:string}[]}[]};
  answer: string;
  sources: ({ id?: string; title: string; url: string | null } & KnowledgeFreshness)[];
  grounded: boolean;
  escalation_suggested: boolean;
}

export interface CourseAttempt {
  id: string;
  assignment_id: string;
  attempt_number: number;
  score_percent: number;
  passed: boolean;
  submitted_at: string;
}

export interface TeamCourseAssignment extends CourseAssignment {
  employee: Pick<EmployeeProfile, 'id' | 'full_name' | 'department' | 'job_title'>;
  course: CourseSummary | null;
}

export interface KnowledgeFreshness {
  version?: string | null;
  updated_at?: string | null;
  reviewed_at?: string | null;
  review_due_at?: string | null;
  freshness?: 'reviewed' | 'unverified' | 'review_overdue';
}

export interface KnowledgeSource extends KnowledgeFreshness {
  id: string;
  title: string;
  content: string;
  source_title: string;
  source_url: string | null;
}

/** Shared contract: live HTTP and explicitly selected demonstration mode. */
export interface HrApi {
  workspace<T>(path: string, method?: string, body?: unknown): Promise<T>;
  readonly mode: 'live' | 'demo';
  getProfile(): Promise<EmployeeProfile>;
  getEmployee(id: string): Promise<EmployeeProfile>;
  getTeam(): Promise<EmployeeProfile[]>;
  getRequests(filters?: RequestFilters): Promise<HrRequest[]>;
  createRequest(payload: RequestCreate, idempotencyKey?: string): Promise<HrRequest>;
  getRequest(id: string): Promise<HrRequest>;
  getRequestHistory(id: string): Promise<RequestEvent[]>;
  reviewRequest(id: string, payload: RequestReview): Promise<HrRequest>;
  getRequestRouting(): Promise<RequestRouting>;
  cancelRequest(id: string): Promise<HrRequest>;
  getNotifications(filters?: NotificationFilters): Promise<Notification[]>;
  markNotificationRead(id: string): Promise<Notification>;
  getCourses(): Promise<Course[]>;
  getMyCourses(): Promise<AssignedCourse[]>;
  getCourse(id: string): Promise<CourseDetail>;
  assignCourse(employeeId: string, courseId: string, dueOn?: string): Promise<CourseAssignment>;
  updateCourseProgress(id: string, percent: number): Promise<CourseAssignment>;
  completeCourse(id: string, answers: Record<string, number>, idempotencyKey?: string): Promise<CourseAssignment>;
  getCourseAttempts(id: string): Promise<CourseAttempt[]>;
  getTeamCourses(filters?: { employee_id?: string; course_id?: string }): Promise<TeamCourseAssignment[]>;
  askJana(question: string): Promise<JanaAnswer>;
  getKnowledgeSource(id: string, version?: string | null): Promise<KnowledgeSource>;
}
