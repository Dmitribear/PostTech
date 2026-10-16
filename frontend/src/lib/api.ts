import type {
  AssignedCourse, AuthResponse, AuthSession, Course, CourseAssignment, CourseDetail,
  EmployeeProfile, HrApi, HrRequest, JanaAnswer, Notification, NotificationFilters,
  RegistrationResponse, RequestCreate, RequestEvent, RequestFilters, RequestReview,
} from './types';

export type { HrApi } from './types';
export const SESSION_KEY = 'jana.hr.session.v1';

const translatedErrors: Record<string, string> = {
  'Invalid email or password': 'Неверный email или пароль.',
  'User has no HR profile; contact an administrator': 'Аккаунт создан, но ещё не связан с профилем сотрудника. Обратитесь в HR.',
  'Supabase Auth is not configured': 'Сервис входа ещё не настроен. Обратитесь к администратору.',
  'Supabase Auth is temporarily unavailable': 'Сервис входа временно недоступен. Попробуйте позже.',
  'Invalid or expired refresh token': 'Сессия завершена. Войдите снова.',
  'Invalid or expired access token': 'Сессия завершена. Войдите снова.',
  'Course is not assigned to you': 'Этот курс пока не назначен вам. Обратитесь к руководителю.',
  'Course is already assigned': 'Этот курс уже назначен сотруднику.',
  'Course is already completed': 'Курс уже завершён.',
  'HR database is not configured': 'Кадровая база ещё не настроена. Обратитесь к администратору.',
  'Request workflow is not installed; apply the database migrations': 'Сервис заявок ещё не настроен. Обратитесь к администратору.',
  'Answer every quiz question exactly once': 'Ответьте на все вопросы теста.',
  'Reviewer role required': 'Для согласования нужна роль руководителя или HR.',
  'You cannot review your own request': 'Нельзя согласовать собственную заявку.',
  'You cannot manage this employee': 'У вас нет доступа к управлению этим сотрудником.',
  'Access to this employee is forbidden': 'У вас нет доступа к данным этого сотрудника.',
  'Manager or HR role required': 'Этот раздел доступен руководителям и HR.',
  'Request was already reviewed': 'По заявке уже принято решение. Обновите её карточку.',
  'Idempotency key was already used with a different request': 'Эта отправка уже использована для другой заявки. Создайте новую заявку.',
  'Request not found': 'Заявка не найдена.',
  'Employee not found': 'Сотрудник не найден.',
  'Notification not found': 'Уведомление не найдено.',
  'Course not found': 'Курс не найден.',
  'Course assignment not found': 'Курс не назначен вам.',
  'This course has no configured quiz': 'Для этого курса ещё не настроен итоговый тест. Обратитесь в HR.',
  'Quiz answer option is invalid': 'Выберите допустимый вариант ответа на каждый вопрос.',
  'HR database operation failed; retry later': 'Кадровая база временно недоступна. Попробуйте позже.',
  'HR database is unavailable; retry later': 'Кадровая база временно недоступна. Попробуйте позже.',
  'Could not complete sign-in with Supabase Auth': 'Не удалось завершить вход. Попробуйте ещё раз.',
  'Could not refresh the Supabase Auth session': 'Не удалось обновить сессию. Попробуйте ещё раз.',
  'Could not refresh session': 'Не удалось обновить сессию. Войдите снова.',
};

function describeDetail(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return translatedErrors[detail] ?? detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item: unknown) => {
      if (item && typeof item === 'object' && 'msg' in item) return String(item.msg);
      return '';
    }).filter(Boolean);
    if (messages.length) return `Проверьте заполненные поля: ${messages.join('; ')}`;
  }
  if (status === 401) return 'Сессия завершена. Войдите снова.';
  if (status === 403) return 'У вас нет доступа к этим данным.';
  if (status === 404) return 'Запись не найдена.';
  if (status === 409) return 'Данные изменились. Обновите страницу и повторите действие.';
  if (status >= 500) return 'Сервис временно недоступен. Попробуйте позже.';
  return 'Не удалось выполнить действие. Попробуйте ещё раз.';
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;
  constructor(status: number, detail?: unknown) {
    super(describeDetail(detail, status));
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Не удалось выполнить действие. Попробуйте ещё раз.';
}

type SessionListener = (session: AuthSession | null) => void;
type StoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export interface LiveApiOptions {
  baseUrl?: string;
  onSessionChange?: SessionListener;
  /** Injectable ports keep transport and token refresh testable without a browser. */
  fetch?: typeof globalThis.fetch;
  storage?: StoragePort | null;
}

function tabStorage(): StoragePort | null {
  try { return typeof window === 'undefined' ? null : window.sessionStorage; }
  catch { return null; }
}

function readSession(storage: StoragePort | null): AuthSession | null {
  try {
    const raw = storage?.getItem(SESSION_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (value && typeof value === 'object' &&
      'access_token' in value && typeof value.access_token === 'string' && value.access_token &&
      'refresh_token' in value && typeof value.refresh_token === 'string' && value.refresh_token &&
      'user_id' in value && typeof value.user_id === 'string' && value.user_id &&
      'email' in value && typeof value.email === 'string' &&
      'token_type' in value && typeof value.token_type === 'string' &&
      'expires_in' in value && typeof value.expires_in === 'number' && Number.isFinite(value.expires_in) && value.expires_in > 0 &&
      'expires_at' in value && typeof value.expires_at === 'number' && Number.isFinite(value.expires_at) && value.expires_at > 0) {
      return value as AuthSession;
    }
    storage?.removeItem(SESSION_KEY);
  } catch {
    try { storage?.removeItem(SESSION_KEY); } catch { /* Storage may be unavailable. */ }
  }
  return null;
}

function queryString(filters: object = {}): string {
  const values = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== '') values.set(key, String(value));
  }
  return values.size ? `?${values.toString()}` : '';
}

export class LiveApi implements HrApi {
  readonly mode = 'live' as const;
  private readonly baseUrl: string;
  private readonly transport: typeof globalThis.fetch;
  private readonly storage: StoragePort | null;
  private session: AuthSession | null;
  private readonly listeners = new Set<SessionListener>();
  private refreshing: Promise<AuthSession> | null = null;
  private sessionVersion = 0;
  private authenticationEpoch = 0;

  constructor(options: LiveApiOptions = {}) {
    this.baseUrl = (options.baseUrl || '/api/v1').replace(/\/+$/, '');
    this.transport = options.fetch ?? globalThis.fetch.bind(globalThis);
    this.storage = options.storage === undefined ? tabStorage() : options.storage;
    this.session = readSession(this.storage);
    if (options.onSessionChange) this.listeners.add(options.onSessionChange);
  }

  getSession(): AuthSession | null { return this.session ? { ...this.session } : null; }

  subscribeSession(listener: SessionListener): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private setSession(session: AuthSession | null, explicitAuthChange = false): void {
    this.session = session;
    this.sessionVersion += 1;
    if (explicitAuthChange || !session) this.authenticationEpoch += 1;
    try {
      if (session) this.storage?.setItem(SESSION_KEY, JSON.stringify(session));
      else this.storage?.removeItem(SESSION_KEY);
    } catch { /* The current tab can still use its in-memory session. */ }
    for (const listener of this.listeners) listener(this.getSession());
  }

  private acceptAuth(response: AuthResponse, explicitAuthChange = false): AuthSession {
    if (!response || typeof response.access_token !== 'string' || !response.access_token ||
      typeof response.refresh_token !== 'string' || !response.refresh_token ||
      typeof response.user_id !== 'string' || !response.user_id || typeof response.email !== 'string' ||
      typeof response.token_type !== 'string' || !Number.isFinite(response.expires_in) || response.expires_in <= 0) {
      throw new ApiError(502, 'Сервис входа вернул некорректную сессию. Попробуйте ещё раз.');
    }
    const session = { ...response, expires_at: Date.now() + response.expires_in * 1000 };
    this.setSession(session, explicitAuthChange);
    return { ...session };
  }

  async login(email: string, password: string): Promise<AuthSession> {
    const result = await this.send<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }, false);
    return this.acceptAuth(result, true);
  }

  async register(email: string, password: string): Promise<RegistrationResponse> {
    const result = await this.send<RegistrationResponse>('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }, false);
    if (result.access_token && result.refresh_token && result.user_id && result.expires_in !== undefined) {
      this.acceptAuth({ user_id: result.user_id, email: result.email, access_token: result.access_token, refresh_token: result.refresh_token, expires_in: result.expires_in, token_type: result.token_type ?? 'bearer' }, true);
    }
    return result;
  }

  logout(): void { this.setSession(null); }

  async refreshSession(): Promise<AuthSession> {
    if (this.refreshing) return this.refreshing;
    const previous = this.session;
    if (!previous) throw new ApiError(401);
    const version = this.sessionVersion;
    const refresh = async (): Promise<AuthSession> => {
      try {
        const result = await this.send<AuthResponse>('/auth/refresh', {
          method: 'POST', body: JSON.stringify({ refresh_token: previous.refresh_token }),
        }, false);
        // A late refresh must never restore a session after logout or replace another login.
        if (version !== this.sessionVersion) {
          if (this.session) return { ...this.session };
          throw new ApiError(401);
        }
        return this.acceptAuth(result);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && version === this.sessionVersion) this.setSession(null);
        throw error;
      }
    };
    this.refreshing = refresh();
    try { return await this.refreshing; }
    finally { this.refreshing = null; }
  }

  private async send<T>(path: string, init: RequestInit = {}, authenticated = true, retry = true): Promise<T> {
    const authenticationEpoch = this.authenticationEpoch;
    if (authenticated && this.session && this.session.expires_at <= Date.now() + 10_000) await this.refreshSession();
    if (authenticated && authenticationEpoch !== this.authenticationEpoch) throw new ApiError(401);
    if (authenticated && !this.session) throw new ApiError(401);
    const accessToken = authenticated ? this.session?.access_token : undefined;
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    if (init.body) headers.set('Content-Type', 'application/json');
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
    let response: Response;
    try { response = await this.transport(`${this.baseUrl}${path}`, { ...init, headers }); }
    catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      throw new ApiError(0, 'Не удалось связаться с сервером. Проверьте подключение и запущен ли API.');
    }
    // Never retry a pending mutation as a different signed-in account.
    if (authenticated && authenticationEpoch !== this.authenticationEpoch) throw new ApiError(401);
    if (response.status === 401 && authenticated && retry && this.session) {
      // Parallel requests that used an old token share the first refresh result.
      if (accessToken === this.session.access_token) await this.refreshSession();
      return this.send<T>(path, init, true, false);
    }
    const raw = await response.text();
    if (authenticated && authenticationEpoch !== this.authenticationEpoch) throw new ApiError(401);
    let payload: unknown;
    try { payload = raw ? JSON.parse(raw) : null; }
    catch { throw new ApiError(response.ok ? 502 : response.status, 'Сервер вернул некорректный ответ. Проверьте адрес API.'); }
    if (!response.ok) {
      if (response.status === 401 && authenticated && this.session?.access_token === accessToken) this.setSession(null);
      const detail = payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : undefined;
      throw new ApiError(response.status, detail);
    }
    return payload as T;
  }

  getProfile(): Promise<EmployeeProfile> { return this.send('/profile'); }
  getEmployee(id: string): Promise<EmployeeProfile> { return this.send(`/employees/${encodeURIComponent(id)}`); }
  getTeam(): Promise<EmployeeProfile[]> { return this.send('/team'); }
  getRequests(filters: RequestFilters = {}): Promise<HrRequest[]> { return this.send(`/requests${queryString(filters)}`); }
  createRequest(payload: RequestCreate, idempotencyKey: string = crypto.randomUUID()): Promise<HrRequest> {
    return this.send('/requests', { method: 'POST', headers: { 'Idempotency-Key': idempotencyKey }, body: JSON.stringify(payload) });
  }
  getRequest(id: string): Promise<HrRequest> { return this.send(`/requests/${encodeURIComponent(id)}`); }
  getRequestHistory(id: string): Promise<RequestEvent[]> { return this.send(`/requests/${encodeURIComponent(id)}/history`); }
  reviewRequest(id: string, payload: RequestReview): Promise<HrRequest> { return this.send(`/requests/${encodeURIComponent(id)}/review`, { method: 'PATCH', body: JSON.stringify(payload) }); }
  getNotifications(filters: NotificationFilters = {}): Promise<Notification[]> { return this.send(`/notifications${queryString(filters)}`); }
  markNotificationRead(id: string): Promise<Notification> { return this.send(`/notifications/${encodeURIComponent(id)}/read`, { method: 'POST' }); }
  getCourses(): Promise<Course[]> { return this.send('/academy/courses'); }
  getMyCourses(): Promise<AssignedCourse[]> { return this.send('/academy/my-courses'); }
  getCourse(id: string): Promise<CourseDetail> { return this.send(`/academy/courses/${encodeURIComponent(id)}`); }
  assignCourse(employeeId: string, courseId: string): Promise<CourseAssignment> { return this.send('/academy/assignments', { method: 'POST', body: JSON.stringify({ employee_id: employeeId, course_id: courseId }) }); }
  updateCourseProgress(id: string, percent: number): Promise<CourseAssignment> { return this.send(`/academy/courses/${encodeURIComponent(id)}/progress`, { method: 'PATCH', body: JSON.stringify({ progress_percent: percent }) }); }
  completeCourse(id: string, answers: Record<string, number>): Promise<CourseAssignment> { return this.send(`/academy/courses/${encodeURIComponent(id)}/complete`, { method: 'POST', body: JSON.stringify({ answers }) }); }
  askJana(question: string): Promise<JanaAnswer> { return this.send('/ai/ask', { method: 'POST', body: JSON.stringify({ question }) }); }
}

export function createLiveApi(options: LiveApiOptions = {}): LiveApi { return new LiveApi(options); }

/** Load the complete permitted request set for totals and calendar views. */
export async function fetchAllRequests(api: HrApi, filters: Omit<RequestFilters, 'limit' | 'offset'> = {}): Promise<HrRequest[]> {
  const records: HrRequest[] = [];
  let offset = 0;
  for (;;) {
    const batch = await api.getRequests({ ...filters, limit: 100, offset });
    records.push(...batch);
    if (batch.length < 100) return records;
    offset += batch.length;
  }
}
