/**
 * Isolated demonstration data. This module never calls the network and is only
 * instantiated after the user explicitly chooses the labelled demo experience.
 * Browser persistence is provided separately by demo-workspace.
 */
import { ApiError } from '@/shared/api/api';
import type {
  AppRole,
  Approver,
  AssignedCourse,
  Course,
  CourseAssignment,
  CourseAttempt,
  CourseDetail,
  EmployeeProfile,
  HrApi,
  HrRequest,
  JanaAnswer,
  KnowledgeSource,
  Notification,
  NotificationFilters,
  RequestCreate,
  RequestEvent,
  RequestFilters,
  RequestReview,
  RequestRouting,
  TeamCourseAssignment,
} from '@/shared/api/contracts';
import { demoLeaveCalendar, LocalDemoJana } from '@/shared/api/localJana';
import { daysBetween } from '@/shared/lib/format';

const uuid = (number: number) => `00000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
const now = () => new Date().toISOString();
function dateAt(offset: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
function timeAt(offset: number): string {
  return new Date(`${dateAt(offset)}T09:00:00+05:00`).toISOString();
}
const demoKnowledge = new Map<string, KnowledgeSource>();
const copy = <T>(value: T): T => structuredClone(value);

function profiles(): EmployeeProfile[] {
  const data: [string, string, string, AppRole][] = [
    ['Алия Серикова', 'Оператор сортировки', 'Хаб Алматы №4', 'worker'],
    ['Ерлан Касымов', 'Руководитель хаба', 'Хаб Алматы №4', 'manager'],
    ['Мадина Утепова', 'HR business partner', 'Люди и культура', 'hr_admin'],
    ['Дарья Ким', 'UX-исследователь', 'Дизайн', 'worker'],
    ['Михаил Петров', 'Frontend-разработчик', 'Разработка', 'worker'],
    ['Алия Садыкова', 'Продуктовый аналитик', 'Аналитика', 'worker'],
    ['Даниил Орлов', 'UI-дизайнер', 'Дизайн', 'worker'],
    ['Сауле Нурова', 'Руководитель HR', 'Люди и культура', 'hr_admin'],
    ['Аскар Омаров', 'Директор', 'Управление', 'director'],
  ];
  return data.map(([full_name, job_title, department, role], i) => ({
    id: uuid(i + 1),
    employee_code: `JN-${String(1042 + i).padStart(4, '0')}`,
    full_name,
    job_title,
    department,
    role,
    email:
      [
        'aliya.serikova',
        'erlan.kasymov',
        'madina.utepova',
        'daria.kim',
        'mikhail.petrov',
        'aliya.sadykova',
        'danil.orlov',
        'saule.nurova',
        'askar.omarov',
      ][i] + '@demo.jana',
    company: 'Jana Post',
    manager_id: role === 'worker' ? uuid(2) : null,
    manager_name: role === 'worker' ? 'Ерлан Касымов' : null,
    hired_at: '2023-03-15',
    vacation_days_remaining: [24, 28, 21, 18, 24, 12, 16, 20, 24][i],
    external_source: 'Демонстрационные данные',
    created_at: timeAt(-500),
    updated_at: timeAt(-1),
  }));
}

function courseData(): (CourseDetail & {
  correctAnswers: Record<string, number>;
})[] {
  const courses: Omit<
    CourseDetail & { correctAnswers: Record<string, number> },
    'active' | 'created_at' | 'assignment'
  >[] = [
    {
      id: uuid(101),
      title: 'Добро пожаловать в Jana',
      description: 'Всё, что нужно для уверенного старта: команда, сервисы и наши принципы.',
      duration_minutes: 15,
      material_markdown:
        '# Рады видеть вас в команде\n\nJana объединяет кадровые сервисы в одном месте. В профиле доступны ваши данные и остаток дней отпуска.\n\n## Ваш рабочий день\n\nНачните с главной страницы: здесь собраны заявки, назначенные курсы и уведомления. За новостями по заявке следите в разделе «Мои заявки».\n\n## Всегда на связи\n\nЕсли нужна помощь с кадровыми вопросами, обратитесь к вашему руководителю или HR. Jana AI помогает найти ответ в опубликованной базе знаний.',
      quiz: [
        {
          id: 'intro-1',
          prompt: 'Где можно посмотреть статус заявки?',
          options: ['В разделе «Мои заявки»', 'В настройках браузера', 'Только по почте'],
        },
        {
          id: 'intro-2',
          prompt: 'Где найти остаток отпускных дней?',
          options: ['В профиле сотрудника', 'В каталоге курсов', 'В истории браузера'],
        },
      ],
      correctAnswers: { 'intro-1': 0, 'intro-2': 0 },
    },
    {
      id: uuid(102),
      title: 'Безопасность персональных данных',
      description: 'Научитесь бережно работать с информацией коллег и защищать свои данные.',
      duration_minutes: 25,
      material_markdown:
        '# Бережно к данным\n\nСотрудник видит собственные кадровые данные. Руководитель работает с данными своей команды, HR — с данными в рамках административной роли.\n\n## Простые правила\n\nНе передавайте пароли и коды подтверждения другим людям. Не отправляйте персональные данные, пароли и токены в AI Jana.\n\n## Если возникли сомнения\n\nСообщите о подозрительной активности администратору. Если Jana не находит подтверждённый ответ в базе знаний, она предлагает обратиться в HR.',
      quiz: [
        {
          id: 'privacy-1',
          prompt: 'Какие данные доступны руководителю?',
          options: ['Любого сотрудника компании', 'Своей команды', 'Только свои'],
        },
        {
          id: 'privacy-2',
          prompt: 'Что делать, если Jana не знает ответ?',
          options: ['Попросить придумать ответ', 'Обратиться в HR', 'Отправить свой пароль'],
        },
      ],
      correctAnswers: { 'privacy-1': 1, 'privacy-2': 1 },
    },
    {
      id: uuid(103),
      title: 'Обратная связь, которая помогает',
      description: 'Как говорить о сложном и превращать обратную связь в развитие.',
      duration_minutes: 35,
      material_markdown:
        '# Разговор с уважением\n\nПолезная обратная связь опирается на конкретные наблюдения, а не на личные оценки.\n\n## Три шага\n\nОпишите ситуацию. Расскажите о наблюдаемом поведении. Объясните, какой результат это дало.\n\n## Диалог\n\nДайте коллеге возможность рассказать о своей точке зрения. Вместе договоритесь о следующем шаге.',
      quiz: [
        {
          id: 'feedback-1',
          prompt: 'С чего лучше начать обратную связь?',
          options: ['С оценки личности', 'С конкретной ситуации и наблюдений', 'С обвинения'],
        },
      ],
      correctAnswers: { 'feedback-1': 1 },
    },
    {
      id: uuid(104),
      title: 'Эффективная работа в команде',
      description: 'Общие цели, понятные договорённости и полезные встречи.',
      duration_minutes: 40,
      material_markdown:
        '# Вместе к результату\n\nСогласуйте общую цель и убедитесь, что каждый понимает свой вклад.\n\n## Договорённости\n\nФиксируйте решения, владельцев задач и сроки. Если планы изменились, расскажите об этом команде заранее.\n\n## Встречи\n\nПриглашайте участников, которым нужна встреча, и отправляйте повестку заранее.',
      quiz: [
        {
          id: 'team-1',
          prompt: 'Что стоит зафиксировать после обсуждения?',
          options: ['Только название встречи', 'Решения, ответственных и сроки', 'Ничего'],
        },
      ],
      correctAnswers: { 'team-1': 1 },
    },
  ];
  return courses.map((course) => ({
    ...course,
    active: true,
    created_at: timeAt(-90),
    assignment: null,
  }));
}

export interface DemoSnapshot {
  employees: EmployeeProfile[];
  assignments: CourseAssignment[];
  requests: HrRequest[];
  history: RequestEvent[];
  notifications: Notification[];
  attempts: CourseAttempt[];
  idempotency: [string, { body: string; id: string }][];
  quizKeys: [string, { fingerprint: string; assignment: CourseAssignment }][];
}

export class DemoApi implements HrApi {
  readonly mode = 'demo' as const;
  private readonly employees = profiles();
  private actor: EmployeeProfile;
  private readonly courses = courseData();
  private readonly assignments: CourseAssignment[] = [];
  private readonly requests: HrRequest[] = [];
  private readonly history: RequestEvent[] = [];
  private readonly notifications: Notification[] = [];
  private readonly idempotency = new Map<string, { body: string; id: string }>();
  private readonly attempts: CourseAttempt[] = [];
  private readonly quizKeys = new Map<
    string,
    { fingerprint: string; assignment: CourseAssignment }
  >();

  get janaAvailable() {
    return Boolean(this.localJana);
  }

  snapshot(): DemoSnapshot {
    return copy({
      employees: this.employees,
      assignments: this.assignments,
      requests: this.requests,
      history: this.history,
      notifications: this.notifications,
      attempts: this.attempts,
      idempotency: [...this.idempotency],
      quizKeys: [...this.quizKeys],
    });
  }

  restore(snapshot: DemoSnapshot) {
    const actorId = this.actor.id;
    const state = copy(snapshot);
    for (const key of [
      'employees',
      'assignments',
      'requests',
      'history',
      'notifications',
      'attempts',
    ] as const) {
      (this[key] as unknown[]).splice(0, this[key].length, ...state[key]);
    }
    this.idempotency.clear();
    for (const [key, value] of state.idempotency) this.idempotency.set(key, value);
    this.quizKeys.clear();
    for (const [key, value] of state.quizKeys) this.quizKeys.set(key, value);
    this.actor = this.employees.find((person) => person.id === actorId)!;
  }
  constructor(
    role: AppRole = 'worker',
    private readonly localJana?: LocalDemoJana,
  ) {
    this.actor = this.employees.find((profile) => profile.role === role)!;
    for (const employee of this.employees) {
      this.assignments.push(
        ...this.courses.slice(0, 3).map((course, index) => ({
          id: crypto.randomUUID(),
          employee_id: employee.id,
          course_id: course.id,
          assigned_by: uuid(3),
          assigned_at: timeAt(-7 - index),
          status:
            index === 0
              ? ('completed' as const)
              : index === 1
                ? ('in_progress' as const)
                : ('not_started' as const),
          progress_percent: index === 0 ? 100 : index === 1 ? 45 : 0,
          score_percent: index === 0 ? 100 : null,
          completed_at: index === 0 ? timeAt(-5) : null,
        })),
      );
    }
    const requests: Partial<HrRequest>[] = [
      {
        employee_id: this.actor.id,
        request_type: 'leave',
        status: 'pending',
        start_date: dateAt(14),
        end_date: dateAt(20),
        comment: 'Семейная поездка. Все задачи передам команде.',
        created_at: timeAt(-1),
      },
      {
        employee_id: this.actor.id,
        request_type: 'advance',
        status: 'approved',
        amount: 50000,
        comment: 'Прошу выплатить аванс.',
        created_at: timeAt(-8),
      },
      {
        employee_id: this.actor.id,
        request_type: 'leave',
        status: 'approved',
        start_date: dateAt(-36),
        end_date: dateAt(-30),
        comment: 'Плановый отпуск.',
        created_at: timeAt(-45),
      },
      {
        employee_id: this.actor.id,
        request_type: 'advance',
        status: 'rejected',
        amount: 80000,
        comment: 'Заявка на аванс.',
        created_at: timeAt(-60),
        reviewer_comment: 'Пожалуйста, согласуйте сумму с HR.',
      },
      ...[uuid(4), uuid(5), uuid(6), uuid(7)].map((employee_id, index) => ({
        employee_id,
        request_type: index % 2 ? ('advance' as const) : ('leave' as const),
        status: index === 2 ? ('approved' as const) : ('pending' as const),
        start_date: index % 2 ? null : dateAt(4 + index * 3),
        end_date: index % 2 ? null : dateAt(8 + index * 3),
        amount: index % 2 ? 40000 + index * 5000 : null,
        comment: index % 2 ? 'Прошу согласовать аванс.' : 'Плановый отпуск, задачи переданы.',
        created_at: timeAt(-index - 1),
      })),
    ];
    requests.forEach((seed, index) => {
      const decided = seed.status === 'approved' || seed.status === 'rejected';
      const record: HrRequest = {
        id: uuid(201 + index),
        employee_id: this.actor.id,
        request_type: 'leave',
        status: 'pending',
        start_date: null,
        end_date: null,
        amount: null,
        comment: '',
        reviewer_comment: decided ? 'Решение согласовано.' : null,
        reviewed_by: decided ? uuid(3) : null,
        reviewed_at: decided ? seed.created_at! : null,
        created_at: timeAt(-1),
        updated_at: seed.created_at!,
        ...seed,
      };
      const routing = this.routing(this.employees.find((p) => p.id === record.employee_id)!);
      Object.assign(record, {
        approval_route: routing.route,
        approvers: routing.approvers,
        cancelled_at: null,
      });
      this.requests.push(record);
      this.history.push({
        id: crypto.randomUUID(),
        request_id: record.id,
        actor_id: record.employee_id,
        event_type: 'created',
        from_status: null,
        to_status: 'pending',
        comment: record.comment,
        created_at: record.created_at,
      });
      if (record.status === 'approved' || record.status === 'rejected')
        this.history.push({
          id: crypto.randomUUID(),
          request_id: record.id,
          actor_id: record.reviewed_by,
          event_type: record.status,
          from_status: 'pending',
          to_status: record.status,
          comment: record.reviewer_comment ?? '',
          created_at: record.reviewed_at!,
        });
    });
    this.notifications.push(
      {
        id: uuid(301),
        employee_id: this.actor.id,
        request_id: null,
        notification_type: 'course_assigned',
        title: 'Время для новых знаний',
        body: 'Вам назначен курс «Безопасность персональных данных». Начните обучение в Jana Academy.',
        read_at: null,
        created_at: timeAt(0),
      },
      {
        id: uuid(302),
        employee_id: this.actor.id,
        request_id: uuid(202),
        notification_type: 'request_approved',
        title: 'Аванс согласован',
        body: 'Ваша заявка на аванс 50 000 ₸ одобрена.',
        read_at: null,
        created_at: timeAt(-1),
      },
      {
        id: uuid(303),
        employee_id: this.actor.id,
        request_id: uuid(201),
        notification_type: 'request_created',
        title: 'Заявка отправлена',
        body: 'Заявка на отпуск передана на рассмотрение.',
        read_at: timeAt(-1),
        created_at: timeAt(-1),
      },
    );
  }

  private canSee(id: string): boolean {
    return (
      id === this.actor.id ||
      this.actor.role === 'hr_admin' ||
      (['manager', 'director'].includes(this.actor.role) &&
        this.employees.some(
          (employee) => employee.id === id && employee.manager_id === this.actor.id,
        ))
    );
  }
  private routing(employee = this.actor): RequestRouting {
    const manager = this.employees.find(
      (p) => p.id === employee.manager_id && p.id !== employee.id && p.role !== 'worker',
    );
    const reviewers = manager
      ? [manager]
      : this.employees.filter((p) => p.role === 'hr_admin' && p.id !== employee.id);
    return {
      can_submit: !!reviewers.length,
      route: manager ? 'manager' : reviewers.length ? 'hr' : 'unassigned',
      approvers: reviewers.map((p) => ({
        id: p.id,
        full_name: p.full_name,
        role: p.role as Approver['role'],
      })),
      message: reviewers.length ? null : 'Нет доступного согласующего. Обратитесь в HR.',
      today: dateAt(0),
      policy:
        'Даты включительно, календарные дни. Баланс из кадровой системы не изменяется автоматически.',
    };
  }
  async getRequestRouting(): Promise<RequestRouting> {
    return copy(this.routing());
  }
  private findRequest(id: string): HrRequest {
    const request = this.requests.find((record) => record.id === id);
    if (!request) throw new ApiError(404);
    if (!this.canSee(request.employee_id)) throw new ApiError(403);
    return request;
  }
  private findCourse(id: string) {
    const course = this.courses.find((record) => record.id === id);
    if (!course) throw new ApiError(404);
    return course;
  }
  private findAssignment(id: string): CourseAssignment {
    const assignment = this.assignments.find(
      (record) => record.course_id === id && record.employee_id === this.actor.id,
    );
    if (!assignment) throw new ApiError(404, 'Курс не назначен вам.');
    return assignment;
  }
  private notify(
    title: string,
    body: string,
    type: string,
    requestId: string | null = null,
    employeeId = this.actor.id,
    courseId: string | null = null,
  ): void {
    this.notifications.unshift({
      id: crypto.randomUUID(),
      employee_id: employeeId,
      request_id: requestId,
      course_id: courseId,
      notification_type: type,
      title,
      body,
      read_at: null,
      created_at: now(),
    });
  }
  async workspace<T>(_path: string, _method = 'GET', _body?: unknown): Promise<T> {
    const [path, query] = _path.split('?');
    if (path === '/leave-balance' && _method === 'GET') {
      const requestId = new URLSearchParams(query).get('request_id');
      const employeeId = requestId ? this.findRequest(requestId).employee_id : this.actor.id;
      const employee = this.employees.find((person) => person.id === employeeId)!;
      const holds = this.requests
        .filter(
          (r) =>
            r.employee_id === employeeId &&
            r.request_type === 'leave' &&
            ['pending', 'approved'].includes(r.status) &&
            r.end_date! >= dateAt(0),
        )
        .map((r) => ({
          request_id: r.id,
          days: daysBetween(r.start_date!, r.end_date!),
          state: r.status,
        }));
      const pending = holds
        .filter((h) => h.state === 'pending')
        .reduce((sum, h) => sum + h.days, 0);
      const approved = holds
        .filter((h) => h.state === 'approved')
        .reduce((sum, h) => sum + h.days, 0);
      return {
        employee_id: employeeId,
        official_days: employee.vacation_days_remaining,
        pending_days: pending,
        approved_unreconciled_days: approved,
        available_days: employee.vacation_days_remaining - pending - approved,
        request_days: holds.find((h) => h.request_id === requestId)?.days ?? 0,
        holds,
      } as T;
    }
    throw new ApiError(409, 'Этот раздел доступен после входа в реальный портал.');
  }
  async getProfile(): Promise<EmployeeProfile> {
    return copy(this.actor);
  }
  async getEmployee(id: string): Promise<EmployeeProfile> {
    const employee = this.employees.find((profile) => profile.id === id);
    if (!employee) throw new ApiError(404);
    if (!this.canSee(id)) throw new ApiError(403);
    return copy(employee);
  }
  async assignEmployeeRole(id: string, role: AppRole) {
    if (this.actor.role !== 'hr_admin') throw new ApiError(403);
    if (id === this.actor.id && role !== 'hr_admin')
      throw new ApiError(409, 'Нельзя снять свою роль HR-администратора.');
    const employee = this.employees.find((person) => person.id === id);
    if (!employee) throw new ApiError(404);
    if (role === 'worker' && this.employees.some((person) => person.manager_id === id))
      throw new ApiError(409, 'Сначала назначьте подчинённым другого руководителя.');
    const previous_role = employee.role;
    employee.role = role;
    return { employee_id: id, previous_role, role };
  }
  async getTeam(): Promise<EmployeeProfile[]> {
    if (this.actor.role === 'worker') throw new ApiError(403);
    return copy(
      this.employees.filter(
        (employee) => this.actor.role === 'hr_admin' || employee.manager_id === this.actor.id,
      ),
    );
  }
  async getCalendarExport(): Promise<Blob> {
    throw new ApiError(409, 'Общий экспорт доступен после входа в портал.');
  }

  async getLeaveCalendar(id: string): Promise<Blob> {
    const record = await this.getRequest(id);
    if (record.request_type !== 'leave' || record.status !== 'approved') throw new ApiError(409);
    return this.localJana ? this.localJana.getLeaveCalendar(record) : demoLeaveCalendar(record);
  }

  async getRequests(filters: RequestFilters = {}): Promise<HrRequest[]> {
    if (filters.employee_id && !this.canSee(filters.employee_id)) throw new ApiError(403);
    const offset = filters.offset ?? 0;
    return copy(
      this.requests
        .filter(
          (record) =>
            this.canSee(record.employee_id) &&
            (filters.scope !== 'mine' || record.employee_id === this.actor.id) &&
            (filters.scope !== 'review' ||
              (this.actor.role !== 'worker' && record.employee_id !== this.actor.id)) &&
            (!filters.employee_id || record.employee_id === filters.employee_id) &&
            (!filters.status || record.status === filters.status) &&
            (!filters.request_type || record.request_type === filters.request_type),
        )
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(offset, offset + (filters.limit ?? 50)),
    );
  }
  async createRequest(
    payload: RequestCreate,
    idempotencyKey: string = crypto.randomUUID(),
  ): Promise<HrRequest> {
    const fingerprint = JSON.stringify({
      request_type: payload.request_type,
      start_date: payload.start_date ?? null,
      end_date: payload.end_date ?? null,
      amount: payload.amount ?? null,
      comment: payload.comment ?? '',
    });
    const submissionKey = `${this.actor.id}:${idempotencyKey}`;
    const previous = this.idempotency.get(submissionKey);
    if (previous) {
      if (previous.body !== fingerprint)
        throw new ApiError(409, 'Эта отправка уже использована для другой заявки.');
      return copy(this.findRequest(previous.id));
    }
    if ((payload.comment?.length ?? 0) > 2000)
      throw new ApiError(422, 'Комментарий не должен превышать 2000 символов.');
    if (payload.request_type === 'leave') {
      const duration = daysBetween(payload.start_date, payload.end_date);
      if (!duration) throw new ApiError(422, 'Укажите корректные даты отпуска.');
      const balance = await this.workspace<{ available_days: number }>('/leave-balance');
      if (duration > balance.available_days)
        throw new ApiError(409, 'Недостаточно дней для выбранного периода');
      if (payload.start_date < dateAt(0))
        throw new ApiError(422, 'Отпуск не может начинаться в прошлом.');
      if (
        this.requests.some(
          (r) =>
            r.employee_id === this.actor.id &&
            r.request_type === 'leave' &&
            ['pending', 'approved'].includes(r.status) &&
            r.start_date! <= payload.end_date &&
            r.end_date! >= payload.start_date,
        )
      )
        throw new ApiError(409, 'Эти даты пересекаются с вашей активной заявкой на отпуск.');
    } else if (
      !Number.isFinite(payload.amount) ||
      payload.amount <= 0 ||
      payload.amount > 1000000 ||
      Math.abs(payload.amount * 100 - Math.round(payload.amount * 100)) > 0.00001
    )
      throw new ApiError(
        422,
        'Укажите сумму от 0,01 до 1 000 000 ₸, не более двух знаков после запятой.',
      );
    const request: HrRequest = {
      id: crypto.randomUUID(),
      employee_id: this.actor.id,
      request_type: payload.request_type,
      start_date: payload.request_type === 'leave' ? payload.start_date : null,
      end_date: payload.request_type === 'leave' ? payload.end_date : null,
      amount: payload.request_type === 'advance' ? payload.amount : null,
      comment: payload.comment ?? '',
      status: 'pending',
      reviewer_comment: null,
      reviewed_at: null,
      reviewed_by: null,
      created_at: now(),
      updated_at: now(),
    };
    const routing = this.routing();
    if (!routing.can_submit) throw new ApiError(409, routing.message);
    Object.assign(request, {
      approval_route: routing.route,
      approvers: routing.approvers,
      cancelled_at: null,
    });
    this.requests.unshift(request);
    this.history.push({
      id: crypto.randomUUID(),
      request_id: request.id,
      actor_id: this.actor.id,
      event_type: 'created',
      from_status: null,
      to_status: 'pending',
      comment: request.comment,
      created_at: request.created_at,
    });
    this.idempotency.set(submissionKey, { body: fingerprint, id: request.id });
    this.notify(
      'Заявка отправлена',
      'Ваша заявка передана на рассмотрение.',
      'request_created',
      request.id,
    );
    for (const reviewer of routing.approvers) {
      this.notify(
        'Новая заявка на согласование',
        `${this.actor.full_name}: ${payload.request_type === 'leave' ? 'отпуск' : 'аванс'}.`,
        'request_created',
        request.id,
        reviewer.id,
      );
    }
    return copy(request);
  }
  async getRequest(id: string): Promise<HrRequest> {
    return copy(this.findRequest(id));
  }
  async getRequestHistory(id: string): Promise<RequestEvent[]> {
    this.findRequest(id);
    return copy(
      this.history
        .filter((event) => event.request_id === id)
        .sort((a, b) => a.created_at.localeCompare(b.created_at)),
    );
  }
  async reviewRequest(id: string, payload: RequestReview): Promise<HrRequest> {
    const request = this.findRequest(id);
    if (this.actor.role === 'worker' || request.employee_id === this.actor.id)
      throw new ApiError(403, 'Вы не можете согласовать эту заявку.');
    if (request.status !== 'pending') {
      if (
        request.status === payload.status &&
        request.reviewed_by === this.actor.id &&
        (request.reviewer_comment ?? '') === (payload.reviewer_comment ?? '')
      )
        return copy(request);
      throw new ApiError(409, 'По этой заявке уже принято решение.');
    }
    if ((payload.reviewer_comment?.length ?? 0) > 2000)
      throw new ApiError(422, 'Комментарий не должен превышать 2000 символов.');
    if (payload.status === 'rejected' && !payload.reviewer_comment?.trim())
      throw new ApiError(422, 'Укажите причину отклонения заявки.');
    Object.assign(request, {
      status: payload.status,
      reviewer_comment: payload.reviewer_comment ?? null,
      reviewed_by: this.actor.id,
      reviewed_at: now(),
      updated_at: now(),
    });
    this.history.push({
      id: crypto.randomUUID(),
      request_id: id,
      actor_id: this.actor.id,
      event_type: payload.status,
      from_status: 'pending',
      to_status: payload.status,
      comment: payload.reviewer_comment ?? '',
      created_at: request.reviewed_at!,
    });
    this.notify(
      payload.status === 'approved' ? 'Заявка одобрена' : 'Заявка отклонена',
      payload.reviewer_comment || 'По вашей заявке принято решение.',
      `request_${payload.status}`,
      id,
      request.employee_id,
    );
    return copy(request);
  }
  async cancelRequest(id: string): Promise<HrRequest> {
    const request = this.findRequest(id);
    if (request.employee_id !== this.actor.id)
      throw new ApiError(403, 'Отозвать заявку может только её автор.');
    if (request.status === 'cancelled') return copy(request);
    if (request.status !== 'pending')
      throw new ApiError(409, 'Отозвать можно только заявку на согласовании.');
    Object.assign(request, {
      status: 'cancelled',
      cancelled_at: now(),
      updated_at: now(),
    });
    this.history.push({
      id: crypto.randomUUID(),
      request_id: id,
      actor_id: this.actor.id,
      event_type: 'cancelled',
      from_status: 'pending',
      to_status: 'cancelled',
      comment: 'Заявка отозвана автором.',
      created_at: now(),
    });
    this.notify('Заявка отозвана', 'Заявка снята с согласования.', 'request_cancelled', id);
    for (const reviewer of request.approvers ?? []) {
      this.notify(
        'Заявка отозвана',
        `${this.actor.full_name} отозвал(а) заявку.`,
        'request_cancelled',
        id,
        reviewer.id,
      );
    }
    return copy(request);
  }
  async getNotifications(filters: NotificationFilters = {}): Promise<Notification[]> {
    const offset = filters.offset ?? 0;
    return copy(
      this.notifications
        .filter(
          (item) =>
            item.employee_id === this.actor.id &&
            (!filters.unread_only || !item.read_at) &&
            (!filters.request_id || item.request_id === filters.request_id),
        )
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(offset, offset + (filters.limit ?? 100)),
    );
  }
  async markNotificationRead(id: string): Promise<Notification> {
    const notification = this.notifications.find(
      (item) => item.id === id && item.employee_id === this.actor.id,
    );
    if (!notification) throw new ApiError(404);
    notification.read_at ??= now();
    return copy(notification);
  }
  async getCourses(): Promise<Course[]> {
    return this.courses.map(({ id, title, description, duration_minutes }) => ({
      id,
      title,
      description,
      duration_minutes,
      category: 'Корпоративные сервисы',
      audience: 'Все сотрудники',
      passing_score: 80,
      assignment: copy(
        this.assignments.find(
          (item) => item.course_id === id && item.employee_id === this.actor.id,
        ) ?? null,
      ),
    }));
  }
  async getMyCourses(): Promise<AssignedCourse[]> {
    return this.assignments
      .filter((item) => item.employee_id === this.actor.id)
      .map((item) => {
        const course = this.findCourse(item.course_id);
        return {
          ...copy(item),
          course: {
            id: course.id,
            title: course.title,
            description: course.description,
            duration_minutes: course.duration_minutes,
          },
        };
      });
  }
  async getCourse(id: string): Promise<CourseDetail> {
    const source = this.findCourse(id);
    const assignment =
      this.assignments.find(
        (item) => item.course_id === id && item.employee_id === this.actor.id,
      ) ?? null;
    if (!assignment && this.actor.role === 'worker')
      throw new ApiError(403, 'Course is not assigned to you');
    const { correctAnswers: _correctAnswers, ...course } = source;
    return copy({
      ...course,
      passing_score: 80,
      category: 'Корпоративные сервисы',
      audience: 'Все сотрудники',
      assignment,
    });
  }
  async assignCourse(employeeId: string, courseId: string): Promise<CourseAssignment> {
    if (
      this.actor.role === 'worker' ||
      (['manager', 'director'].includes(this.actor.role) &&
        !this.employees.some(
          (profile) => profile.id === employeeId && profile.manager_id === this.actor.id,
        ))
    )
      throw new ApiError(403);
    await this.getEmployee(employeeId);
    this.findCourse(courseId);
    const existing = this.assignments.find(
      (item) => item.employee_id === employeeId && item.course_id === courseId,
    );
    if (existing) throw new ApiError(409, 'Course is already assigned');
    const assignment: CourseAssignment = {
      id: crypto.randomUUID(),
      course_id: courseId,
      employee_id: employeeId,
      assigned_by: this.actor.id,
      assigned_at: now(),
      status: 'not_started',
      progress_percent: 0,
      score_percent: null,
      completed_at: null,
    };
    this.assignments.push(assignment);
    this.notify(
      'Назначено обучение',
      'Вам назначен новый курс Jana Academy.',
      'course_assigned',
      null,
      employeeId,
      courseId,
    );
    return copy(assignment);
  }
  async updateCourseProgress(id: string, percent: number): Promise<CourseAssignment> {
    const assignment = this.findAssignment(id);
    if (assignment.status === 'completed') return copy(assignment);
    if (!Number.isInteger(percent) || percent < 0 || percent > 99)
      throw new ApiError(422, 'Прогресс должен быть от 0 до 99.');
    assignment.progress_percent = Math.max(assignment.progress_percent, percent);
    assignment.status = assignment.progress_percent ? 'in_progress' : 'not_started';
    if (assignment.progress_percent >= 90) assignment.material_completed_at ??= now();
    return copy(assignment);
  }
  async completeCourse(
    id: string,
    answers: Record<string, number>,
    idempotencyKey = crypto.randomUUID(),
  ): Promise<CourseAssignment> {
    const course = this.findCourse(id);
    const assignment = this.findAssignment(id);
    if (assignment.status === 'completed') return copy(assignment);
    const key = `${this.actor.id}:${id}:${idempotencyKey}`;
    const fingerprint = JSON.stringify(Object.entries(answers).sort());
    const previous = this.quizKeys.get(key);
    if (previous) {
      if (previous.fingerprint !== fingerprint)
        throw new ApiError(409, 'Повторная отправка содержит другие ответы.');
      return copy(previous.assignment);
    }
    if (!assignment.material_completed_at)
      throw new ApiError(409, 'Сначала изучите материал курса.');
    if (
      Object.keys(answers).length !== course.quiz.length ||
      course.quiz.some(
        (question) =>
          !Number.isInteger(answers[question.id]) ||
          answers[question.id] < 0 ||
          answers[question.id] >= question.options.length,
      )
    )
      throw new ApiError(422, 'Answer every quiz question exactly once');
    const correct = course.quiz.filter(
      (question) => answers[question.id] === course.correctAnswers[question.id],
    ).length;
    assignment.score_percent = Math.round((correct / course.quiz.length) * 10000) / 100;
    const passed = assignment.score_percent >= 80;
    assignment.status = passed ? 'completed' : 'in_progress';
    assignment.progress_percent = passed ? 100 : 90;
    assignment.completed_at = passed ? now() : null;
    assignment.last_attempt_at = now();
    assignment.attempt_count = (assignment.attempt_count || 0) + 1;
    this.attempts.push({
      id: crypto.randomUUID(),
      assignment_id: assignment.id,
      attempt_number: assignment.attempt_count,
      score_percent: assignment.score_percent,
      passed,
      submitted_at: now(),
    });
    this.quizKeys.set(key, { fingerprint, assignment: copy(assignment) });
    if (passed)
      this.notify(
        'Обучение завершено',
        `Курс «${course.title}» пройден. Результат: ${assignment.score_percent}%.`,
        'course_completed',
        null,
        this.actor.id,
        id,
      );
    if (passed && this.actor.manager_id)
      this.notify(
        'Обучение завершено',
        `${this.actor.full_name} завершил(а) курс «${course.title}».`,
        'team_course_completed',
        null,
        this.actor.manager_id,
        id,
      );
    return copy(assignment);
  }
  async getCourseAttempts(id: string): Promise<CourseAttempt[]> {
    const assignment = this.findAssignment(id);
    return copy(
      this.attempts
        .filter((a) => a.assignment_id === assignment.id)
        .sort((a, b) => b.attempt_number - a.attempt_number),
    );
  }
  async getTeamCourses(
    filters: { employee_id?: string; course_id?: string } = {},
  ): Promise<TeamCourseAssignment[]> {
    const team = await this.getTeam();
    if (filters.employee_id && !team.some((p) => p.id === filters.employee_id))
      throw new ApiError(403);
    return copy(
      this.assignments
        .filter(
          (a) =>
            team.some((p) => p.id === a.employee_id) &&
            (!filters.employee_id || filters.employee_id === a.employee_id) &&
            (!filters.course_id || filters.course_id === a.course_id),
        )
        .map((a) => {
          const { id, title, description, duration_minutes } = this.findCourse(a.course_id);
          const person = team.find((p) => p.id === a.employee_id)!;
          return {
            ...a,
            employee: {
              id: person.id,
              full_name: person.full_name,
              department: person.department,
              job_title: person.job_title,
            },
            course: {
              id,
              title,
              description,
              duration_minutes,
              passing_score: 80,
            },
          };
        }),
    );
  }
  async getKnowledgeSource(id: string): Promise<KnowledgeSource> {
    const source = demoKnowledge.get(id);
    if (!source) throw new ApiError(404);
    return copy(source);
  }
  async askJana(question: string): Promise<JanaAnswer> {
    if (this.localJana) return this.localJana.askJana(question);
    if (question.trim().length < 3 || question.length > 2000)
      throw new ApiError(422, 'Напишите вопрос длиной от 3 до 2000 символов.');
    const query = question.toLowerCase();
    let answer = '';
    let source = '';
    let actions: JanaAnswer['actions'] = [];
    if (/отпуск|отдых|vacation|leave/.test(query)) {
      answer =
        'На главной нажмите «Оформить отпуск», выберите в календаре даты начала и окончания и нажмите «Продолжить». Проверьте заявку и согласующих, затем нажмите «Отправить заявку». Комментарий необязателен — добавьте его при необходимости. Начало должно быть сегодня или позже; даты не должны пересекаться с действующим отпуском.\n\nПосле отправки дни резервируются. Доступные дни видны на главной, в профиле и при оформлении; кадровый остаток и доступный остаток с учётом резервов различаются. Решение и историю можно посмотреть в карточке заявки. Автор не согласует собственную заявку.';
      source = 'Демо: порядок оформления отпуска';
      actions = [{ id: 'leave_new', label: 'Оформить отпуск', href: '/calendar?select=1' }];
    } else if (/аванс|выплат|advance/.test(query)) {
      answer =
        'На главной нажмите «Запросить аванс» или создайте заявку типа «Аванс» в разделе «Заявки». Укажите положительную сумму в тенге, при необходимости добавьте необязательный комментарий, проверьте и отправьте заявку. Даты отпуска не заполняются.\n\nРешение принимает назначенный руководитель или HR по показанному маршруту; автор не согласует свою заявку. Статус и комментарий согласующего, если он указан, доступны в карточке заявки. Одобрение само по себе не выполняет банковский перевод; срок выплаты уточняют в HR.';
      source = 'Демо: порядок оформления аванса';
      actions = [
        { id: 'advance_new', label: 'Запросить аванс', href: '/requests/new?type=advance' },
      ];
    } else if (/заявк|статус/.test(query)) {
      answer =
        'Откройте «Мои заявки» и нужную карточку: там видны статус, маршрут и история согласования, а также комментарий руководителя или HR, если он указан. «На согласовании» означает ожидание решения, «Согласовано» — положительное решение, «Отклонено» — отказ, «Отозвана» — автор отозвал заявку до решения.\n\nПосле решения появится уведомление. Согласование и оформление документа HR — разные этапы: согласованная заявка может ещё ожидать оформления. Общий ответ Jana не проверяет статус конкретной персональной заявки.';
      source = 'Демо: руководство по работе с заявками';
      actions = [{ id: 'requests_mine', label: 'Мои заявки', href: '/requests' }];
    } else if (/обуч|курс|academy|учеб/.test(query)) {
      answer =
        'Откройте «Обучение» и назначенный вам курс. Изучите материал; если есть отдельные уроки, завершите каждый до перехода к тесту. Ответьте на все вопросы и нажмите «Завершить тест». Результат и история попыток доступны в карточке курса.\n\nДля завершения нужен проходной балл, показанный именно в карточке этого курса; по умолчанию это 80%. Если баллов не хватило, результат сохраняется, курс остаётся в процессе и тест можно повторить. Курсы назначает HR, а руководитель или директор — своим прямым подчинённым. Наличие курса в каталоге ещё не означает, что он вам назначен.';
      source = 'Демо: руководство по Jana Academy';
      actions = [{ id: 'academy', label: 'Обучение', href: '/academy' }];
    } else if (/профил|данн|доступ|роль/.test(query)) {
      answer =
        'Кадровые сведения в разделе «Мой профиль», включая телефон, доступны сотруднику только для чтения. Для исправления обратитесь в HR. Сотрудник видит собственный профиль и свои заявки. Руководитель и директор видят профили и обучение только своих прямых подчинённых; HR-администратор — профили и заявки всех сотрудников. Личные уведомления видны только получателю.\n\nЗамещение не открывает все профили и обучение команды. Роль в рабочем портале назначает HR; выбор роли в демонстрации действует только в демо. Jana не раскрывает персональные сведения других работников и не меняет права доступа.';
      source = 'Демо: политика доступа к кадровым данным';
      actions = [{ id: 'profile', label: 'Мой профиль', href: '/profile' }];
    }
    const sourceId = source
      ? uuid(
          900 +
            [
              'Демо: порядок оформления отпуска',
              'Демо: порядок оформления аванса',
              'Демо: руководство по работе с заявками',
              'Демо: руководство по Jana Academy',
              'Демо: политика доступа к кадровым данным',
            ].indexOf(source),
        )
      : '';
    if (sourceId)
      demoKnowledge.set(sourceId, {
        id: sourceId,
        title: source,
        content: answer,
        source_title: source,
        source_url: null,
      });
    return {
      answer:
        answer ||
        'В демонстрационной базе Jana нет подтверждённой информации по этому вопросу. Обратитесь в HR. Я могу подсказать, как оформить отпуск или аванс, пройти обучение и посмотреть профиль.',
      sources: source ? [{ id: sourceId, title: source, url: null }] : [],
      actions,
      grounded: Boolean(source),
      escalation_suggested: !source,
    };
  }
}

export function createDemoApi(role: AppRole = 'worker', localJana?: LocalDemoJana): DemoApi {
  return new DemoApi(role, localJana);
}
