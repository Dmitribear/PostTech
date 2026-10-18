import type { TelegramLink, TelegramStatus } from '@/shared/api/contracts';
import type {
  AppRole,
  CalendarExportFilters,
  AssignedCourse,
  AuthResponse,
  AuthSession,
  Course,
  CourseAssignment,
  CourseAttempt,
  CourseDetail,
  PersonalCourseInput,
  EmployeeProfile,
  HrApi,
  HrRequest,
  InvitationCompletion,
  InvitationInput,
  InvitationPreview,
  InvitationRecord,
  IssuedInvitation,
  JanaAnswer,
  KnowledgeSource,
  Notification,
  NotificationFilters,
  RegistrationInput,
  RegistrationResponse,
  RegistrationVerification,
  RequestCreate,
  RequestEvent,
  RequestFilters,
  RequestReview,
  RequestRouting,
  TeamCourseAssignment,
} from '@/shared/api/contracts';
import { getLocale, t } from '@/shared/lib/i18n';

export type { HrApi } from '@/shared/api/contracts';
export const SESSION_KEY = 'jana.hr.session.v1';

const translatedErrors: Record<string, string> = {
  'Telegram integration is not configured':
    'Подключение Telegram ещё не настроено. Обратитесь к администратору.',
  'Telegram is already linked; unlink it first':
    'Telegram уже подключён. Обновите статус или сначала отключите текущий аккаунт.',
  'Telegram account is not linked':
    'Telegram пока не подключён. Обновите статус и подключите аккаунт.',
  'Telegram is temporarily unavailable': 'Telegram временно недоступен. Попробуйте позже.',

  'Source not found': 'Источник больше не опубликован или недоступен.',
  'Jana AI is busy. Try again shortly':
    'Jana сейчас отвечает на другие вопросы. Повторите вопрос немного позже.',
  'Jana AI is temporarily unavailable': 'Jana сейчас недоступна. Попробуйте ещё раз.',
  'Jana knowledge base is temporarily unavailable':
    'База знаний Jana временно недоступна. Попробуйте ещё раз.',
  'Calendar changed while loading; retry the export':
    'Список отпусков изменился. Повторите экспорт.',
  'Too many leave events; choose a narrower date range or employee':
    'Слишком много отпусков. Выберите меньший период.',
  'Team calendar requires a reviewer role': 'Командный календарь доступен руководителю и HR.',
  'Calendar end date must not precede its start date':
    'Дата окончания должна быть не раньше даты начала.',
  'Calendar export requires an approved leave request':
    'Файл доступен только для одобренного отпуска.',
  'HR role required': 'Раздел доступен HR',
  'Invalid delegation dates or participants':
    'Проверьте участников и даты замещения. Максимальный срок — 365 дней.',
  'Both participants must be managers or HR': 'Выберите руководителя или HR для обеих ролей.',
  'Overlapping delegation or delegation chain':
    'В эти даты уже действует замещение или цепочка замещений.',
  'Deputy is on approved leave': 'Заместитель в эти даты находится в согласованном отпуске.',
  'Operation key already used':
    'Эта операция уже выполнена с другими данными. Откройте форму заново.',
  'Course changed; reload before saving':
    'Курс изменён другим HR. Обновите страницу перед сохранением.',
  'Published courses are immutable; create a new version':
    'Создайте новую версию опубликованного курса.',
  'Completed learning is immutable': 'Завершённое обучение нельзя изменить.',
  'Deadline cannot be in the past': 'Срок обучения не может быть в прошлом.',
  'Confirm sharing with HR': 'Подтвердите передачу текста в HR.',
  'No HR recipient available': 'Нет доступного сотрудника HR для ответа.',
  'Another HR must answer your question': 'На ваш вопрос должен ответить другой сотрудник HR.',
  'Ticket already answered': 'На обращение уже ответили. Обновите карточку.',
  'Ticket not found': 'Обращение не найдено.',
  'Course content or translation is invalid':
    'Проверьте материал и перевод курса: вопросы и порядок ответов должны совпадать.',
  'Course content required': 'Заполните материал курса.',
  'Delegation not found': 'Замещение не найдено.',

  'Invitation code is invalid': 'Код приглашения не найден. Проверьте его или обратитесь в HR.',
  'Invitation has expired or was revoked. Contact HR for a new code':
    'Приглашение истекло или отозвано. Попросите новый код у HR.',
  'Invitation has already been used. Sign in to your account':
    'Приглашение уже активировано. Войдите с почтой и паролем.',
  'Invitation has already been used': 'Приглашение уже активировано.',
  'Invitation not found': 'Приглашение не найдено.',
  'Invitation email sender is not configured':
    'Отправка приглашений не настроена. Добавьте RESEND_API_KEY на сервере.',
  'You cannot remove your own HR administrator role': 'Нельзя снять свою роль HR-администратора.',
  "Reassign this employee's direct reports before removing their supervisor role":
    'Сначала назначьте подчинённым другого руководителя.',
  'HR administrator role required': 'Приглашения доступны только HR-администратору.',
  'Invitation lifetime must be between 1 and 168 hours': 'Срок приглашения — от 1 часа до 7 дней.',
  'Invitation manager must be a manager or HR administrator':
    'Выберите руководителя или HR-администратора.',
  'An employee profile already exists for this email or employee code':
    'Сотрудник с такой почтой или табельным номером уже существует.',
  'An active invitation already exists for this employee':
    'Сотруднику уже выдано приглашение. При необходимости отзовите его во вкладке «Выданные».',
  'Please wait 60 seconds before requesting another email':
    'Повторное письмо можно запросить через минуту.',
  'Please wait 60 seconds before trying again':
    'Слишком много попыток. Подождите минуту и повторите.',
  'Create your account before requesting a confirmation email':
    'Сначала заполните данные аккаунта.',
  'Enter your first and last name': 'Укажите имя и фамилию.',
  'Enter your first and last name to activate your workspace':
    'Укажите имя и фамилию для активации профиля.',
  'Confirm the invited email before activating your workspace':
    'Сначала подтвердите почту из приглашения.',
  'Create your account before activating your workspace':
    'Сначала заполните имя и фамилию на шаге создания аккаунта.',
  'Your reporting manager has changed. Contact HR':
    'Данные руководителя изменились. Обратитесь в HR.',
  'An employee profile already exists. Contact HR':
    'Профиль сотрудника уже существует. Обратитесь в HR.',
  'Invitation registration is not configured. Contact HR':
    'Регистрация по приглашению ещё не настроена. Обратитесь в HR.',
  'Registration is temporarily unavailable. Try again later':
    'Регистрация временно недоступна. Попробуйте позже.',
  'An account already exists. Confirm your email, then continue with your password':
    'Аккаунт уже существует. Подтвердите почту и выберите «Уже подтвердили почту?».',
  'Confirmation email could not be sent. Contact HR or try again later':
    'Письмо не удалось отправить. Попробуйте позже или обратитесь в HR.',
  'Could not create your account. Check your password or contact HR':
    'Не удалось создать аккаунт. Проверьте пароль или обратитесь в HR.',
  'Could not complete registration with Supabase Auth':
    'Не удалось завершить регистрацию. Попробуйте ещё раз.',
  'Confirmation code is invalid or expired. Request a new code':
    'Код неверный или истёк. Проверьте письмо или запросите новый код.',
  'Could not verify your email. Try again later':
    'Не удалось подтвердить почту. Попробуйте ещё раз.',
  'Use the email address from your invitation': 'Используйте почту из приглашения.',
  'Confirm your email and check your password':
    'Подтвердите почту по ссылке из письма и проверьте пароль.',
  'Invalid email or password': 'Неверный email или пароль.',
  'User has no HR profile; contact an administrator':
    'Аккаунт создан, но ещё не связан с профилем сотрудника. Обратитесь в HR.',
  'Supabase Auth is not configured': 'Сервис входа ещё не настроен. Обратитесь к администратору.',
  'Supabase Auth is temporarily unavailable': 'Сервис входа временно недоступен. Попробуйте позже.',
  'Reset code is invalid or expired. Request a new code':
    'Код неверный или истёк. Запросите новый код.',
  'Password could not be changed. Choose a different password and request a new code':
    'Выберите другой пароль и запросите новый код.',
  'Password update could not be confirmed. Try signing in with your new password or request a new code':
    'Не удалось подтвердить смену пароля. Попробуйте войти с новым паролем или запросите новый код.',
  'Please wait before requesting another reset code': 'Подождите перед повторной отправкой кода.',
  'Too many reset attempts. Try again later':
    'Слишком много попыток. Подождите и попробуйте снова.',
  'Invalid or expired refresh token': 'Сессия завершена. Войдите снова.',
  'Invalid or expired access token': 'Сессия завершена. Войдите снова.',
  'Course is not assigned to you': 'Этот курс пока не назначен вам. Обратитесь к руководителю.',
  'Course is already assigned': 'Этот курс уже назначен сотруднику.',
  'Course is already completed': 'Курс уже завершён.',
  'HR database is not configured': 'Кадровая база ещё не настроена. Обратитесь к администратору.',
  'Request workflow is not installed; apply the database migrations':
    'Сервис заявок ещё не настроен. Обратитесь к администратору.',
  'Answer every quiz question exactly once': 'Ответьте на все вопросы теста.',
  'Reviewer role required': 'Для согласования нужна роль руководителя или HR.',
  'You cannot review your own request': 'Нельзя согласовать собственную заявку.',
  'You cannot manage this employee': 'У вас нет доступа к управлению этим сотрудником.',
  'Access to this employee is forbidden': 'У вас нет доступа к данным этого сотрудника.',
  'Manager or HR role required': 'Этот раздел доступен руководителям и HR.',
  'Request was already reviewed': 'По заявке уже принято решение. Обновите её карточку.',
  'Idempotency key was already used with a different request':
    'Эта отправка уже использована для другой заявки. Создайте новую заявку.',
  'Request not found': 'Заявка не найдена.',
  'Employee not found': 'Сотрудник не найден.',
  'Notification not found': 'Уведомление не найдено.',
  'Course not found': 'Курс не найден.',
  'Course assignment not found': 'Курс не назначен вам.',
  'This course has no configured quiz':
    'Для этого курса ещё не настроен итоговый тест. Обратитесь в HR.',
  'Quiz answer option is invalid': 'Выберите допустимый вариант ответа на каждый вопрос.',
  'HR database operation failed; retry later':
    'Кадровая база временно недоступна. Попробуйте позже.',
  'HR database is unavailable; retry later': 'Кадровая база временно недоступна. Попробуйте позже.',
  'Could not complete sign-in with Supabase Auth': 'Не удалось завершить вход. Попробуйте ещё раз.',
  'Could not refresh the Supabase Auth session': 'Не удалось обновить сессию. Попробуйте ещё раз.',
  'Could not refresh session': 'Не удалось обновить сессию. Войдите снова.',
  'No eligible approver is configured; contact HR':
    'Нет доступного согласующего. Обратитесь в HR для настройки маршрута.',
  'Leave cannot start in the past': 'Дата начала отпуска не может быть в прошлом.',
  'Leave overlaps an existing pending or approved request':
    'Даты пересекаются с вашим согласованным отпуском или заявкой на рассмотрении.',
  'A reason is required to reject a request': 'Укажите причину отклонения заявки.',
  'You are not an assigned approver for this request': 'Вы не назначены согласующим этой заявки.',
  'Request is no longer pending': 'Заявка уже обработана или отозвана. Обновите карточку.',
  'Only the owner can cancel a request': 'Отозвать заявку может только её автор.',
  'Only pending requests can be cancelled':
    'Отозвать можно только заявку, которая ещё ожидает решения.',
  'Read the course material before submitting the quiz':
    'Сначала изучите материал курса и отметьте его прочитанным.',
  'Course material is not configured': 'Учебный материал пока не опубликован. Обратитесь в HR.',
  'Course quiz configuration is invalid': 'В настройках теста есть ошибка. Обратитесь в HR.',
  'Quiz submission key was already used for different answers':
    'Эта попытка уже отправлена с другими ответами. Откройте тест заново.',
  'Academy workflow is not installed; apply the database migrations':
    'Сервис обучения ещё не настроен. Обратитесь к администратору.',
  'Academy is temporarily unavailable; retry later':
    'Jana Academy временно недоступна. Повторите попытку позже.',
  'Knowledge source not found': 'Источник больше не опубликован или недоступен.',
};

function describeDetail(detail: unknown, status: number): string {
  if (typeof detail === 'string' && detail.trim()) return translatedErrors[detail] ?? detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item: unknown) => {
        if (item && typeof item === 'object' && 'msg' in item) {
          const message = String(item.msg);
          const friendly: Record<string, string> = {
            'Value error, Password must contain an uppercase letter and a number':
              'Пароль должен содержать заглавную букву и цифру',
            'Value error, Enter a valid name': 'Укажите имя и фамилию',
            'Value error, Value cannot be blank': 'Заполните обязательные поля',
          };
          return friendly[message] ?? message;
        }
        return '';
      })
      .filter(Boolean);
    if (messages.length)
      return getLocale() === 'kk'
        ? 'Енгізілген өрістерді тексеріңіз: міндетті мәндерді толтырып, шектеулерді сақтаңыз.'
        : `Проверьте заполненные поля: ${messages.join('; ')}`;
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
  readonly retryAfterSeconds?: number;
  constructor(status: number, detail?: unknown, retryAfterSeconds?: number) {
    super(describeDetail(detail, status));
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

export function errorMessage(error: unknown): string {
  return t(
    error instanceof Error ? error.message : 'Не удалось выполнить действие. Попробуйте ещё раз.',
  );
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
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

function browserStorage(): { storage: StoragePort | null; shared: boolean } {
  try {
    if (typeof window === 'undefined') return { storage: null, shared: false };
    const storage = window.localStorage;
    const probe = `${SESSION_KEY}.probe`;
    storage.setItem(probe, '1');
    storage.removeItem(probe);
    // A stored null is a logout marker: an older tab must not restore its legacy session.
    if (storage.getItem(SESSION_KEY) === null) {
      const previous = tabStorage()?.getItem(SESSION_KEY);
      if (previous) storage.setItem(SESSION_KEY, previous);
    }
    tabStorage()?.removeItem(SESSION_KEY);
    return { storage, shared: true };
  } catch {
    return { storage: tabStorage(), shared: false };
  }
}

function readSession(storage: StoragePort | null): AuthSession | null {
  try {
    const raw = storage?.getItem(SESSION_KEY);
    if (!raw || raw === 'null') return null;
    const value: unknown = JSON.parse(raw);
    if (
      value &&
      typeof value === 'object' &&
      'access_token' in value &&
      typeof value.access_token === 'string' &&
      value.access_token &&
      'refresh_token' in value &&
      typeof value.refresh_token === 'string' &&
      value.refresh_token &&
      'user_id' in value &&
      typeof value.user_id === 'string' &&
      value.user_id &&
      'email' in value &&
      typeof value.email === 'string' &&
      'token_type' in value &&
      typeof value.token_type === 'string' &&
      'expires_in' in value &&
      typeof value.expires_in === 'number' &&
      Number.isFinite(value.expires_in) &&
      value.expires_in > 0 &&
      'expires_at' in value &&
      typeof value.expires_at === 'number' &&
      Number.isFinite(value.expires_at) &&
      value.expires_at > 0
    ) {
      return value as AuthSession;
    }
    storage?.removeItem(SESSION_KEY);
  } catch {
    try {
      storage?.removeItem(SESSION_KEY);
    } catch {
      /* Storage may be unavailable. */
    }
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
  getTelegramStatus(): Promise<TelegramStatus> {
    return this.send('/telegram/status');
  }
  async createTelegramLink(): Promise<TelegramLink> {
    return validateTelegramLink(
      await this.send<TelegramLink>('/telegram/link', { method: 'POST' }),
    );
  }
  async unlinkTelegram(): Promise<void> {
    await this.send('/telegram/link', { method: 'DELETE' });
  }
  setTelegramNotifications(enabled: boolean): Promise<TelegramStatus> {
    return this.send('/telegram/settings', {
      method: 'PATCH',
      body: JSON.stringify({ notifications_enabled: enabled }),
    });
  }

  readonly mode = 'live' as const;
  private readonly baseUrl: string;
  private readonly transport: typeof globalThis.fetch;
  private readonly storage: StoragePort | null;
  private readonly sharedStorage: boolean;
  private session: AuthSession | null;
  private readonly listeners = new Set<SessionListener>();
  private refreshing: Promise<AuthSession> | null = null;
  private sessionVersion = 0;
  private authenticationEpoch = 0;

  constructor(options: LiveApiOptions = {}) {
    this.baseUrl = (options.baseUrl || '/api/v1').replace(/\/+$/, '');
    this.transport = options.fetch ?? globalThis.fetch.bind(globalThis);
    const browser = options.storage === undefined ? browserStorage() : null;
    this.storage = browser ? browser.storage : (options.storage ?? null);
    this.sharedStorage = browser?.shared ?? false;
    this.session = readSession(this.storage);
    if (options.onSessionChange) this.subscribeSession(options.onSessionChange);
  }

  getSession(): AuthSession | null {
    return this.session ? { ...this.session } : null;
  }

  subscribeSession(listener: SessionListener): () => void {
    this.listeners.add(listener);
    const sync = (event: StorageEvent) => {
      if (
        (event.key === SESSION_KEY || event.key === null) &&
        (!event.storageArea || event.storageArea === this.storage)
      )
        this.syncSession();
    };
    if (this.sharedStorage) window.addEventListener('storage', sync);
    return () => {
      this.listeners.delete(listener);
      if (this.sharedStorage) window.removeEventListener('storage', sync);
    };
  }

  private syncSession(): void {
    if (!this.sharedStorage) return;
    const session = readSession(this.storage);
    if (JSON.stringify(session) !== JSON.stringify(this.session))
      this.setSession(session, session?.user_id !== this.session?.user_id, false);
  }

  private setSession(
    session: AuthSession | null,
    explicitAuthChange = false,
    persist = true,
  ): void {
    this.session = session;
    this.sessionVersion += 1;
    if (explicitAuthChange || !session) this.authenticationEpoch += 1;
    try {
      if (persist) {
        if (session || this.sharedStorage)
          this.storage?.setItem(SESSION_KEY, JSON.stringify(session));
        else this.storage?.removeItem(SESSION_KEY);
      }
    } catch {
      /* The current tab can still use its in-memory session. */
    }
    for (const listener of this.listeners) listener(this.getSession());
  }

  private acceptAuth(response: AuthResponse, explicitAuthChange = false): AuthSession {
    if (
      !response ||
      typeof response.access_token !== 'string' ||
      !response.access_token ||
      typeof response.refresh_token !== 'string' ||
      !response.refresh_token ||
      typeof response.user_id !== 'string' ||
      !response.user_id ||
      typeof response.email !== 'string' ||
      typeof response.token_type !== 'string' ||
      !Number.isFinite(response.expires_in) ||
      response.expires_in <= 0
    ) {
      throw new ApiError(502, 'Сервис входа вернул некорректную сессию. Попробуйте ещё раз.');
    }
    const session = {
      ...response,
      expires_at: Date.now() + response.expires_in * 1000,
    };
    this.setSession(session, explicitAuthChange);
    return { ...session };
  }

  async login(email: string, password: string): Promise<AuthSession> {
    const result = await this.send<AuthResponse>(
      '/auth/login',
      { method: 'POST', body: JSON.stringify({ email, password }) },
      false,
    );
    return this.acceptAuth(result, true);
  }

  async requestPasswordReset(email: string): Promise<{ message: string; retry_after: number }> {
    const result = await this.send<{ message: string; retry_after: number }>(
      '/auth/password-reset',
      { method: 'POST', body: JSON.stringify({ email }) },
      false,
    );
    if (
      !result ||
      typeof result.message !== 'string' ||
      !result.message ||
      !Number.isFinite(result.retry_after) ||
      result.retry_after <= 0
    )
      throw new ApiError(502);
    return result;
  }

  async confirmPasswordReset(input: {
    email: string;
    token: string;
    password: string;
  }): Promise<{ message: string }> {
    // Recovery verifies control of the email but never creates a portal session.
    const result = await this.send<{ message: string }>(
      '/auth/password-reset/confirm',
      { method: 'POST', body: JSON.stringify(input) },
      false,
    );
    if (!result || typeof result.message !== 'string' || !result.message) throw new ApiError(502);
    return result;
  }

  async checkInvitation(invitation_code: string): Promise<InvitationPreview> {
    return this.send<InvitationPreview>(
      '/auth/invitations/check',
      { method: 'POST', body: JSON.stringify({ invitation_code }) },
      false,
    );
  }

  async register(input: RegistrationInput): Promise<RegistrationResponse> {
    const result = await this.send<RegistrationResponse>(
      '/auth/register',
      { method: 'POST', body: JSON.stringify(input) },
      false,
    );
    if (
      result.access_token &&
      result.refresh_token &&
      result.user_id &&
      result.expires_in !== undefined
    ) {
      this.acceptAuth(
        {
          user_id: result.user_id,
          email: result.email,
          access_token: result.access_token,
          refresh_token: result.refresh_token,
          expires_in: result.expires_in,
          token_type: result.token_type ?? 'bearer',
        },
        true,
      );
    }
    return result;
  }

  async verifyRegistration(input: RegistrationVerification): Promise<AuthSession> {
    const result = await this.send<AuthResponse>(
      '/auth/verify-registration',
      { method: 'POST', body: JSON.stringify(input) },
      false,
    );
    return this.acceptAuth(result, true);
  }

  async resendRegistration(
    invitation_code: string,
  ): Promise<{ message: string; retry_after: number }> {
    return this.send(
      '/auth/resend-registration',
      { method: 'POST', body: JSON.stringify({ invitation_code }) },
      false,
    );
  }

  async completeInvitation(input: InvitationCompletion): Promise<AuthSession> {
    const result = await this.send<AuthResponse>(
      '/auth/complete-invitation',
      { method: 'POST', body: JSON.stringify(input) },
      false,
    );
    return this.acceptAuth(result, true);
  }

  async issueInvitation(input: InvitationInput): Promise<IssuedInvitation> {
    return this.send('/auth/invitations', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  }

  async getCalendarExport(filters: CalendarExportFilters = {}): Promise<Blob> {
    return new Blob([await this.send<string>(`/requests/calendar.ics${queryString(filters)}`)], {
      type: 'text/calendar',
    });
  }

  async getLeaveCalendar(id: string): Promise<Blob> {
    return new Blob([await this.send<string>(`/requests/${encodeURIComponent(id)}/calendar.ics`)], {
      type: 'text/calendar',
    });
  }

  async getInvitations(): Promise<InvitationRecord[]> {
    return this.send('/auth/invitations');
  }

  async getJanaSource(id: string): Promise<KnowledgeSource> {
    return this.send(janaSourcePath(id));
  }

  async sendInvitation(id: string): Promise<IssuedInvitation> {
    return this.send(`/auth/invitations/${encodeURIComponent(id)}/send`, {
      method: 'POST',
    });
  }

  async revokeInvitation(id: string): Promise<{ id: string; revoked: boolean }> {
    return this.send(`/auth/invitations/${encodeURIComponent(id)}/revoke`, {
      method: 'POST',
    });
  }

  logout(): void {
    this.setSession(null);
  }

  async refreshSession(): Promise<AuthSession> {
    if (this.refreshing) return this.refreshing;
    this.syncSession();
    const previous = this.session;
    if (!previous) throw new ApiError(401);
    const epoch = this.authenticationEpoch;
    const refresh = async (): Promise<AuthSession> => {
      this.syncSession();
      if (!this.session || epoch !== this.authenticationEpoch) throw new ApiError(401);
      // Another tab may have rotated the token while we waited for the browser lock.
      if (this.session.refresh_token !== previous.refresh_token) return { ...this.session };
      const version = this.sessionVersion;
      try {
        const result = await this.send<AuthResponse>(
          '/auth/refresh',
          {
            method: 'POST',
            body: JSON.stringify({ refresh_token: previous.refresh_token }),
          },
          false,
        );
        this.syncSession();
        // A late refresh must never restore a session after logout or replace another login.
        if (version !== this.sessionVersion) {
          if (this.session && epoch === this.authenticationEpoch) return { ...this.session };
          throw new ApiError(401);
        }
        return this.acceptAuth(result);
      } catch (error) {
        this.syncSession();
        if (version !== this.sessionVersion && this.session && epoch === this.authenticationEpoch)
          return { ...this.session };
        if (error instanceof ApiError && error.status === 401 && version === this.sessionVersion)
          this.setSession(null);
        throw error;
      }
    };
    this.refreshing =
      this.sharedStorage && typeof navigator !== 'undefined' && navigator.locks
        ? navigator.locks.request(`${SESSION_KEY}:${this.baseUrl}`, refresh)
        : refresh();
    try {
      return await this.refreshing;
    } finally {
      this.refreshing = null;
    }
  }

  private async send<T>(
    path: string,
    init: RequestInit = {},
    authenticated = true,
    retry = true,
  ): Promise<T> {
    if (authenticated) this.syncSession();
    const authenticationEpoch = this.authenticationEpoch;
    if (authenticated && this.session && this.session.expires_at <= Date.now() + 10_000)
      await this.refreshSession();
    if (authenticated && authenticationEpoch !== this.authenticationEpoch) throw new ApiError(401);
    if (authenticated && !this.session) throw new ApiError(401);
    const accessToken = authenticated ? this.session?.access_token : undefined;
    const headers = new Headers(init.headers);
    headers.set(
      'Accept',
      path.split('?')[0].endsWith('/calendar.ics') ? 'text/calendar' : 'application/json',
    );
    headers.set('Accept-Language', getLocale());
    if (init.body) headers.set('Content-Type', 'application/json');
    if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`);
    let response: Response;
    try {
      response = await this.transport(`${this.baseUrl}${path}`, {
        ...init,
        headers,
      });
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') throw error;
      throw new ApiError(
        0,
        'Не удалось связаться с сервером. Проверьте подключение и запущен ли API.',
      );
    }
    // Never retry a pending mutation as a different signed-in account.
    if (authenticated) this.syncSession();
    if (authenticated && authenticationEpoch !== this.authenticationEpoch) throw new ApiError(401);
    if (response.status === 401 && authenticated && retry && this.session) {
      // Parallel requests that used an old token share the first refresh result.
      if (accessToken === this.session.access_token) await this.refreshSession();
      return this.send<T>(path, init, true, false);
    }
    const raw = await response.text();
    if (authenticated) this.syncSession();
    if (authenticated && authenticationEpoch !== this.authenticationEpoch) throw new ApiError(401);
    if (response.ok && path.split('?')[0].endsWith('/calendar.ics')) {
      if (
        !response.headers.get('Content-Type')?.startsWith('text/calendar') ||
        !raw.startsWith('BEGIN:VCALENDAR')
      )
        throw new ApiError(502, 'Некорректный файл календаря');
      return raw as T;
    }
    let payload: unknown;
    try {
      payload = raw ? JSON.parse(raw) : null;
    } catch {
      // FastAPI/proxies can return plain text or HTML for an HTTP failure.
      // Preserve that status; only successful non-JSON responses imply a bad API URL.
      if (response.ok)
        throw new ApiError(502, 'Сервер вернул некорректный ответ. Проверьте адрес API.');
    }
    if (!response.ok) {
      if (response.status === 401 && authenticated && this.session?.access_token === accessToken)
        this.setSession(null);
      const detail =
        payload && typeof payload === 'object' && 'detail' in payload ? payload.detail : undefined;
      const retryAfter = Number(response.headers.get('Retry-After'));
      throw new ApiError(
        response.status,
        detail,
        Number.isFinite(retryAfter) && retryAfter > 0 ? Math.ceil(retryAfter) : undefined,
      );
    }
    return payload as T;
  }

  workspace<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
    return this.send(`/workspace${path}`, {
      method,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  }
  getProfile(): Promise<EmployeeProfile> {
    return this.send('/profile');
  }
  assignEmployeeRole(
    id: string,
    role: AppRole,
  ): Promise<{ employee_id: string; previous_role: AppRole; role: AppRole }> {
    return this.send(`/admin/employees/${encodeURIComponent(id)}/role`, {
      method: 'PATCH',
      body: JSON.stringify({ role }),
    });
  }
  getEmployee(id: string): Promise<EmployeeProfile> {
    return this.send(`/employees/${encodeURIComponent(id)}`);
  }
  getTeam(): Promise<EmployeeProfile[]> {
    return this.send('/team');
  }
  getRequests(filters: RequestFilters = {}): Promise<HrRequest[]> {
    return this.send(`/requests${queryString(filters)}`);
  }
  createRequest(
    payload: RequestCreate,
    idempotencyKey: string = crypto.randomUUID(),
  ): Promise<HrRequest> {
    return this.send('/requests', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify(payload),
    });
  }
  getRequest(id: string): Promise<HrRequest> {
    return this.send(`/requests/${encodeURIComponent(id)}`);
  }
  getRequestHistory(id: string): Promise<RequestEvent[]> {
    return this.send(`/requests/${encodeURIComponent(id)}/history`);
  }
  reviewRequest(id: string, payload: RequestReview): Promise<HrRequest> {
    return this.send(`/requests/${encodeURIComponent(id)}/review`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }
  getRequestRouting(): Promise<RequestRouting> {
    return this.send('/requests/routing');
  }
  cancelRequest(id: string): Promise<HrRequest> {
    return this.send(`/requests/${encodeURIComponent(id)}/cancel`, {
      method: 'POST',
    });
  }
  getNotifications(filters: NotificationFilters = {}): Promise<Notification[]> {
    return this.send(`/notifications${queryString(filters)}`);
  }
  markNotificationRead(id: string): Promise<Notification> {
    return this.send(`/notifications/${encodeURIComponent(id)}/read`, {
      method: 'POST',
    });
  }
  getCourses(): Promise<Course[]> {
    return this.send('/academy/courses');
  }
  getMyCourses(): Promise<AssignedCourse[]> {
    return this.send('/academy/my-courses');
  }
  getCourse(id: string): Promise<CourseDetail> {
    return this.send(`/academy/courses/${encodeURIComponent(id)}`);
  }

  createPersonalCourse(input: PersonalCourseInput): Promise<CourseAssignment> {
    return this.send('/academy/personal-courses', { method: 'POST', body: JSON.stringify(input) });
  }
  enrollExternalCourse(id: string): Promise<CourseAssignment> {
    return this.send(`/academy/courses/${encodeURIComponent(id)}/enroll`, { method: 'POST' });
  }
  assignCourse(employeeId: string, courseId: string, dueOn?: string): Promise<CourseAssignment> {
    return this.send('/academy/assignments', {
      method: 'POST',
      body: JSON.stringify({
        employee_id: employeeId,
        course_id: courseId,
        due_on: dueOn || null,
      }),
    });
  }
  updateCourseProgress(id: string, percent: number): Promise<CourseAssignment> {
    return this.send(`/academy/courses/${encodeURIComponent(id)}/progress`, {
      method: 'PATCH',
      body: JSON.stringify({ progress_percent: percent }),
    });
  }
  completeCourse(
    id: string,
    answers: Record<string, number>,
    idempotencyKey = crypto.randomUUID(),
  ): Promise<CourseAssignment> {
    return this.send(`/academy/courses/${encodeURIComponent(id)}/complete`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ answers }),
    });
  }
  getCourseAttempts(id: string): Promise<CourseAttempt[]> {
    return this.send(`/academy/courses/${encodeURIComponent(id)}/attempts`);
  }
  getTeamCourses(
    filters: { employee_id?: string; course_id?: string } = {},
  ): Promise<TeamCourseAssignment[]> {
    return this.send(`/academy/team${queryString(filters)}`);
  }
  askJana(question: string): Promise<JanaAnswer> {
    return this.send('/ai/ask', {
      method: 'POST',
      body: JSON.stringify({ question }),
    });
  }
  getKnowledgeSource(id: string, version?: string | null): Promise<KnowledgeSource> {
    return this.send(
      `/ai/sources/${encodeURIComponent(id)}${version ? `?version=${encodeURIComponent(version)}` : ''}`,
    );
  }
}

export function createLiveApi(options: LiveApiOptions = {}): LiveApi {
  return new LiveApi(options);
}

/** Load the complete permitted request set for totals and calendar views. */
export async function fetchAllRequests(
  api: HrApi,
  filters: Omit<RequestFilters, 'limit' | 'offset'> = {},
): Promise<HrRequest[]> {
  const records: HrRequest[] = [];
  let offset = 0;
  for (;;) {
    const batch = await api.getRequests({ ...filters, limit: 100, offset });
    records.push(...batch);
    if (batch.length < 100) return records;
    offset += batch.length;
  }
}

export function janaSourcePath(id: string): string {
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id))
    throw new ApiError(502, 'Сервер вернул некорректную ссылку на источник.');
  return `/ai/sources/${id}`;
}

export async function calendarBlob(response: Response): Promise<Blob> {
  if (response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'text/calendar')
    throw new ApiError(502, 'Сервер вернул некорректный файл календаря.');
  return response.blob();
}

/** A one-use linking secret may only be opened at Telegram's canonical HTTPS endpoint. */
export function validateTelegramLink(value: TelegramLink): TelegramLink {
  try {
    const url = new URL(value.url);
    const params = [...url.searchParams.keys()];
    if (
      url.protocol !== 'https:' ||
      url.hostname !== 't.me' ||
      url.port ||
      url.username ||
      url.password ||
      url.hash ||
      !/^\/[a-zA-Z0-9_]{5,32}$/.test(url.pathname) ||
      params.length !== 1 ||
      params[0] !== 'start' ||
      !/^[a-zA-Z0-9_-]{1,64}$/.test(url.searchParams.get('start') || '') ||
      !Number.isFinite(Date.parse(value.expires_at)) ||
      Date.parse(value.expires_at) <= Date.now()
    )
      throw new Error();
    return value;
  } catch {
    throw new ApiError(502, 'Сервер вернул некорректную ссылку Telegram. Попробуйте снова.');
  }
}
