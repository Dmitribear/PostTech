/**
 * Isolated demonstration data. This module never calls the network and is only
 * instantiated after the user explicitly chooses the labelled demo experience.
 * Mutations last for this instance only; they never update employee records.
 */
import { ApiError } from './api';
import { daysBetween } from './format';
import type {
  AppRole, AssignedCourse, Course, CourseAssignment, CourseDetail, EmployeeProfile,
  HrApi, HrRequest, JanaAnswer, Notification, NotificationFilters, RequestCreate,
  RequestEvent, RequestFilters, RequestReview,
} from './types';

const uuid = (number: number) => `00000000-0000-4000-8000-${String(number).padStart(12, '0')}`;
const now = () => new Date().toISOString();
function dateAt(offset: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
function timeAt(offset: number): string { return new Date(`${dateAt(offset)}T09:00:00+05:00`).toISOString(); }
const copy = <T,>(value: T): T => structuredClone(value);

function profiles(): EmployeeProfile[] {
  const data: [string, string, string, AppRole][] = [
    ['Алия Серикова', 'Оператор сортировки', 'Хаб Алматы №4', 'worker'],
    ['Ерлан Касымов', 'Руководитель хаба', 'Хаб Алматы №4', 'manager'],
    ['Мадина Утепова', 'HR business partner', 'Люди и культура', 'hr_admin'],
    ['Дарья Ким', 'UX-исследователь', 'Дизайн', 'worker'],
    ['Михаил Петров', 'Frontend-разработчик', 'Разработка', 'worker'],
    ['Алия Садыкова', 'Продуктовый аналитик', 'Аналитика', 'worker'],
    ['Даниил Орлов', 'UI-дизайнер', 'Дизайн', 'worker'],
  ];
  return data.map(([full_name, job_title, department, role], i) => ({
    id: uuid(i + 1), employee_code: `JN-${String(1042 + i).padStart(4, '0')}`,
    full_name, job_title, department, role, email: ['aliya.serikova', 'erlan.kasymov', 'madina.utepova', 'daria.kim', 'mikhail.petrov', 'aliya.sadykova', 'danil.orlov'][i] + '@demo.jana',
    company: 'Jana Post', manager_id: role === 'worker' ? uuid(2) : null,
    hired_at: '2023-03-15', vacation_days_remaining: [24, 28, 21, 18, 24, 12, 16][i],
    external_source: 'Демонстрационные данные', created_at: timeAt(-500), updated_at: timeAt(-1),
  }));
}

function courseData(): (CourseDetail & { correctAnswers: Record<string, number> })[] {
  const courses: Omit<CourseDetail & { correctAnswers: Record<string, number> }, 'active' | 'created_at' | 'assignment'>[] = [
    {
      id: uuid(101), title: 'Добро пожаловать в Jana', description: 'Всё, что нужно для уверенного старта: команда, сервисы и наши принципы.', duration_minutes: 15,
      material_markdown: '# Рады видеть вас в команде\n\nJana объединяет кадровые сервисы в одном месте. В профиле доступны ваши данные и остаток дней отпуска.\n\n## Ваш рабочий день\n\nНачните с главной страницы: здесь собраны заявки, назначенные курсы и уведомления. За новостями по заявке следите в разделе «Мои заявки».\n\n## Всегда на связи\n\nЕсли нужна помощь с кадровыми вопросами, обратитесь к вашему руководителю или HR. Jana AI помогает найти ответ в опубликованной базе знаний.',
      quiz: [{ id: 'intro-1', prompt: 'Где можно посмотреть статус заявки?', options: ['В разделе «Мои заявки»', 'В настройках браузера', 'Только по почте'] }, { id: 'intro-2', prompt: 'Где найти остаток отпускных дней?', options: ['В профиле сотрудника', 'В каталоге курсов', 'В истории браузера'] }], correctAnswers: { 'intro-1': 0, 'intro-2': 0 },
    },
    {
      id: uuid(102), title: 'Безопасность персональных данных', description: 'Научитесь бережно работать с информацией коллег и защищать свои данные.', duration_minutes: 25,
      material_markdown: '# Бережно к данным\n\nСотрудник видит собственные кадровые данные. Руководитель работает с данными своей команды, HR — с данными в рамках административной роли.\n\n## Простые правила\n\nНе передавайте пароли и коды подтверждения другим людям. Не отправляйте персональные данные, пароли и токены в AI Jana.\n\n## Если возникли сомнения\n\nСообщите о подозрительной активности администратору. Если Jana не находит подтверждённый ответ в базе знаний, она предлагает обратиться в HR.',
      quiz: [{ id: 'privacy-1', prompt: 'Какие данные доступны руководителю?', options: ['Любого сотрудника компании', 'Своей команды', 'Только свои'] }, { id: 'privacy-2', prompt: 'Что делать, если Jana не знает ответ?', options: ['Попросить придумать ответ', 'Обратиться в HR', 'Отправить свой пароль'] }], correctAnswers: { 'privacy-1': 1, 'privacy-2': 1 },
    },
    {
      id: uuid(103), title: 'Обратная связь, которая помогает', description: 'Как говорить о сложном и превращать обратную связь в развитие.', duration_minutes: 35,
      material_markdown: '# Разговор с уважением\n\nПолезная обратная связь опирается на конкретные наблюдения, а не на личные оценки.\n\n## Три шага\n\nОпишите ситуацию. Расскажите о наблюдаемом поведении. Объясните, какой результат это дало.\n\n## Диалог\n\nДайте коллеге возможность рассказать о своей точке зрения. Вместе договоритесь о следующем шаге.',
      quiz: [{ id: 'feedback-1', prompt: 'С чего лучше начать обратную связь?', options: ['С оценки личности', 'С конкретной ситуации и наблюдений', 'С обвинения'] }], correctAnswers: { 'feedback-1': 1 },
    },
    {
      id: uuid(104), title: 'Эффективная работа в команде', description: 'Общие цели, понятные договорённости и полезные встречи.', duration_minutes: 40,
      material_markdown: '# Вместе к результату\n\nСогласуйте общую цель и убедитесь, что каждый понимает свой вклад.\n\n## Договорённости\n\nФиксируйте решения, владельцев задач и сроки. Если планы изменились, расскажите об этом команде заранее.\n\n## Встречи\n\nПриглашайте участников, которым нужна встреча, и отправляйте повестку заранее.',
      quiz: [{ id: 'team-1', prompt: 'Что стоит зафиксировать после обсуждения?', options: ['Только название встречи', 'Решения, ответственных и сроки', 'Ничего'] }], correctAnswers: { 'team-1': 1 },
    },
  ];
  return courses.map(course => ({ ...course, active: true, created_at: timeAt(-90), assignment: null }));
}

export class DemoApi implements HrApi {
  readonly mode = 'demo' as const;
  private readonly employees = profiles();
  private readonly actor: EmployeeProfile;
  private readonly courses = courseData();
  private readonly assignments: CourseAssignment[] = [];
  private readonly requests: HrRequest[] = [];
  private readonly history: RequestEvent[] = [];
  private readonly notifications: Notification[] = [];
  private readonly idempotency = new Map<string, { body: string; id: string }>();

  constructor(role: AppRole = 'worker') {
    this.actor = this.employees.find(profile => profile.role === role)!;
    for (const employee of this.employees) {
      this.assignments.push(...this.courses.slice(0, 3).map((course, index) => ({
        id: crypto.randomUUID(), employee_id: employee.id, course_id: course.id,
        assigned_by: uuid(3), assigned_at: timeAt(-7 - index),
        status: index === 0 ? 'completed' as const : index === 1 ? 'in_progress' as const : 'not_started' as const,
        progress_percent: index === 0 ? 100 : index === 1 ? 45 : 0,
        score_percent: index === 0 ? 100 : null, completed_at: index === 0 ? timeAt(-5) : null,
      })));
    }
    const requests: Partial<HrRequest>[] = [
      { employee_id: this.actor.id, request_type: 'leave', status: 'pending', start_date: dateAt(14), end_date: dateAt(20), comment: 'Семейная поездка. Все задачи передам команде.', created_at: timeAt(-1) },
      { employee_id: this.actor.id, request_type: 'advance', status: 'approved', amount: 50000, comment: 'Прошу выплатить аванс.', created_at: timeAt(-8) },
      { employee_id: this.actor.id, request_type: 'leave', status: 'approved', start_date: dateAt(-36), end_date: dateAt(-30), comment: 'Плановый отпуск.', created_at: timeAt(-45) },
      { employee_id: this.actor.id, request_type: 'advance', status: 'rejected', amount: 80000, comment: 'Заявка на аванс.', created_at: timeAt(-60), reviewer_comment: 'Пожалуйста, согласуйте сумму с HR.' },
      ...[uuid(4), uuid(5), uuid(6), uuid(7)].map((employee_id, index) => ({ employee_id, request_type: index % 2 ? 'advance' as const : 'leave' as const, status: index === 2 ? 'approved' as const : 'pending' as const, start_date: index % 2 ? null : dateAt(4 + index * 3), end_date: index % 2 ? null : dateAt(8 + index * 3), amount: index % 2 ? 40000 + index * 5000 : null, comment: index % 2 ? 'Прошу согласовать аванс.' : 'Плановый отпуск, задачи переданы.', created_at: timeAt(-index - 1) })),
    ];
    requests.forEach((seed, index) => {
      const decided = seed.status === 'approved' || seed.status === 'rejected';
      const record: HrRequest = {
        id: uuid(201 + index), employee_id: this.actor.id, request_type: 'leave', status: 'pending',
        start_date: null, end_date: null, amount: null, comment: '', reviewer_comment: decided ? 'Решение согласовано.' : null,
        reviewed_by: decided ? uuid(3) : null, reviewed_at: decided ? seed.created_at! : null,
        created_at: timeAt(-1), updated_at: seed.created_at!, ...seed,
      };
      this.requests.push(record);
      this.history.push({ id: crypto.randomUUID(), request_id: record.id, actor_id: record.employee_id, event_type: 'created', from_status: null, to_status: 'pending', comment: record.comment, created_at: record.created_at });
      if (record.status === 'approved' || record.status === 'rejected') this.history.push({ id: crypto.randomUUID(), request_id: record.id, actor_id: record.reviewed_by, event_type: record.status, from_status: 'pending', to_status: record.status, comment: record.reviewer_comment ?? '', created_at: record.reviewed_at! });
    });
    this.notifications.push(
      { id: uuid(301), employee_id: this.actor.id, request_id: null, notification_type: 'course_assigned', title: 'Время для новых знаний', body: 'Вам назначен курс «Безопасность персональных данных». Начните обучение в Jana Academy.', read_at: null, created_at: timeAt(0) },
      { id: uuid(302), employee_id: this.actor.id, request_id: uuid(202), notification_type: 'request_approved', title: 'Аванс согласован', body: 'Ваша заявка на аванс 50 000 ₸ одобрена.', read_at: null, created_at: timeAt(-1) },
      { id: uuid(303), employee_id: this.actor.id, request_id: uuid(201), notification_type: 'request_created', title: 'Заявка отправлена', body: 'Заявка на отпуск передана на рассмотрение.', read_at: timeAt(-1), created_at: timeAt(-1) },
    );
  }

  private canSee(id: string): boolean { return id === this.actor.id || this.actor.role === 'hr_admin' || (this.actor.role === 'manager' && this.employees.some(employee => employee.id === id && employee.manager_id === this.actor.id)); }
  private findRequest(id: string): HrRequest {
    const request = this.requests.find(record => record.id === id);
    if (!request) throw new ApiError(404);
    if (!this.canSee(request.employee_id)) throw new ApiError(403);
    return request;
  }
  private findCourse(id: string) {
    const course = this.courses.find(record => record.id === id);
    if (!course) throw new ApiError(404);
    return course;
  }
  private findAssignment(id: string): CourseAssignment {
    const assignment = this.assignments.find(record => record.course_id === id && record.employee_id === this.actor.id);
    if (!assignment) throw new ApiError(404, 'Курс не назначен вам.');
    return assignment;
  }
  private notify(title: string, body: string, type: string, requestId: string | null = null, employeeId = this.actor.id): void {
    this.notifications.unshift({ id: crypto.randomUUID(), employee_id: employeeId, request_id: requestId, notification_type: type, title, body, read_at: null, created_at: now() });
  }
  async getProfile(): Promise<EmployeeProfile> { return copy(this.actor); }
  async getEmployee(id: string): Promise<EmployeeProfile> {
    const employee = this.employees.find(profile => profile.id === id);
    if (!employee) throw new ApiError(404);
    if (!this.canSee(id)) throw new ApiError(403);
    return copy(employee);
  }
  async getTeam(): Promise<EmployeeProfile[]> {
    if (this.actor.role === 'worker') throw new ApiError(403);
    return copy(this.employees.filter(employee => this.actor.role === 'hr_admin' || employee.manager_id === this.actor.id));
  }
  async getRequests(filters: RequestFilters = {}): Promise<HrRequest[]> {
    if (filters.employee_id && !this.canSee(filters.employee_id)) throw new ApiError(403);
    const offset = filters.offset ?? 0;
    return copy(this.requests.filter(record => this.canSee(record.employee_id) &&
      (!filters.employee_id || record.employee_id === filters.employee_id) &&
      (!filters.status || record.status === filters.status) &&
      (!filters.request_type || record.request_type === filters.request_type))
      .sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(offset, offset + (filters.limit ?? 50)));
  }
  async createRequest(payload: RequestCreate, idempotencyKey: string = crypto.randomUUID()): Promise<HrRequest> {
    const fingerprint = JSON.stringify({ request_type: payload.request_type, start_date: payload.start_date ?? null, end_date: payload.end_date ?? null, amount: payload.amount ?? null, comment: payload.comment ?? '' });
    const previous = this.idempotency.get(idempotencyKey);
    if (previous) {
      if (previous.body !== fingerprint) throw new ApiError(409, 'Эта отправка уже использована для другой заявки.');
      return copy(this.findRequest(previous.id));
    }
    if ((payload.comment?.length ?? 0) > 2000) throw new ApiError(422, 'Комментарий не должен превышать 2000 символов.');
    if (payload.request_type === 'leave') {
      const duration = daysBetween(payload.start_date, payload.end_date);
      if (!duration) throw new ApiError(422, 'Укажите корректные даты отпуска.');
    } else if (!Number.isFinite(payload.amount) || payload.amount <= 0 || payload.amount > 1000000 || Math.abs(payload.amount * 100 - Math.round(payload.amount * 100)) > 0.00001) throw new ApiError(422, 'Укажите сумму от 0,01 до 1 000 000 ₸, не более двух знаков после запятой.');
    const request: HrRequest = { id: crypto.randomUUID(), employee_id: this.actor.id, request_type: payload.request_type, start_date: payload.request_type === 'leave' ? payload.start_date : null, end_date: payload.request_type === 'leave' ? payload.end_date : null, amount: payload.request_type === 'advance' ? payload.amount : null, comment: payload.comment ?? '', status: 'pending', reviewer_comment: null, reviewed_at: null, reviewed_by: null, created_at: now(), updated_at: now() };
    this.requests.unshift(request);
    this.history.push({ id: crypto.randomUUID(), request_id: request.id, actor_id: this.actor.id, event_type: 'created', from_status: null, to_status: 'pending', comment: request.comment, created_at: request.created_at });
    this.idempotency.set(idempotencyKey, { body: fingerprint, id: request.id });
    this.notify('Заявка отправлена', 'Ваша заявка передана на рассмотрение.', 'request_created', request.id);
    return copy(request);
  }
  async getRequest(id: string): Promise<HrRequest> { return copy(this.findRequest(id)); }
  async getRequestHistory(id: string): Promise<RequestEvent[]> {
    this.findRequest(id);
    return copy(this.history.filter(event => event.request_id === id).sort((a, b) => a.created_at.localeCompare(b.created_at)));
  }
  async reviewRequest(id: string, payload: RequestReview): Promise<HrRequest> {
    const request = this.findRequest(id);
    if (this.actor.role === 'worker' || request.employee_id === this.actor.id) throw new ApiError(403, 'Вы не можете согласовать эту заявку.');
    if (request.status !== 'pending') {
      if (request.status === payload.status && request.reviewed_by === this.actor.id && (request.reviewer_comment ?? '') === (payload.reviewer_comment ?? '')) return copy(request);
      throw new ApiError(409, 'По этой заявке уже принято решение.');
    }
    if ((payload.reviewer_comment?.length ?? 0) > 2000) throw new ApiError(422, 'Комментарий не должен превышать 2000 символов.');
    Object.assign(request, { status: payload.status, reviewer_comment: payload.reviewer_comment ?? null, reviewed_by: this.actor.id, reviewed_at: now(), updated_at: now() });
    this.history.push({ id: crypto.randomUUID(), request_id: id, actor_id: this.actor.id, event_type: payload.status, from_status: 'pending', to_status: payload.status, comment: payload.reviewer_comment ?? '', created_at: request.reviewed_at! });
    this.notify(payload.status === 'approved' ? 'Заявка одобрена' : 'Заявка отклонена', payload.reviewer_comment || 'По вашей заявке принято решение.', `request_${payload.status}`, id, request.employee_id);
    return copy(request);
  }
  async getNotifications(filters: NotificationFilters = {}): Promise<Notification[]> {
    const offset = filters.offset ?? 0;
    return copy(this.notifications.filter(item => item.employee_id === this.actor.id && (!filters.unread_only || !item.read_at) && (!filters.request_id || item.request_id === filters.request_id)).sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(offset, offset + (filters.limit ?? 100)));
  }
  async markNotificationRead(id: string): Promise<Notification> {
    const notification = this.notifications.find(item => item.id === id && item.employee_id === this.actor.id);
    if (!notification) throw new ApiError(404);
    notification.read_at ??= now();
    return copy(notification);
  }
  async getCourses(): Promise<Course[]> {
    return this.courses.map(({ id, title, description, duration_minutes }) => ({ id, title, description, duration_minutes, assignment: copy(this.assignments.find(item => item.course_id === id && item.employee_id === this.actor.id) ?? null) }));
  }
  async getMyCourses(): Promise<AssignedCourse[]> {
    return this.assignments.filter(item => item.employee_id === this.actor.id).map(item => {
      const course = this.findCourse(item.course_id);
      return { ...copy(item), course: { id: course.id, title: course.title, description: course.description, duration_minutes: course.duration_minutes } };
    });
  }
  async getCourse(id: string): Promise<CourseDetail> {
    const source = this.findCourse(id);
    const assignment = this.assignments.find(item => item.course_id === id && item.employee_id === this.actor.id) ?? null;
    if (!assignment && this.actor.role !== 'hr_admin') throw new ApiError(403, 'Course is not assigned to you');
    const { correctAnswers: _correctAnswers, ...course } = source;
    return copy({ ...course, assignment });
  }
  async assignCourse(employeeId: string, courseId: string): Promise<CourseAssignment> {
    if (this.actor.role === 'worker' || (this.actor.role === 'manager' && !this.employees.some(profile => profile.id === employeeId && profile.manager_id === this.actor.id))) throw new ApiError(403);
    await this.getEmployee(employeeId);
    this.findCourse(courseId);
    if (this.assignments.some(item => item.employee_id === employeeId && item.course_id === courseId)) throw new ApiError(409, 'Course is already assigned');
    const assignment: CourseAssignment = { id: crypto.randomUUID(), course_id: courseId, employee_id: employeeId, assigned_by: this.actor.id, assigned_at: now(), status: 'not_started', progress_percent: 0, score_percent: null, completed_at: null };
    this.assignments.push(assignment);
    this.notify('Назначено обучение', 'Вам назначен новый курс Jana Academy.', 'course_assigned', null, employeeId);
    return copy(assignment);
  }
  async updateCourseProgress(id: string, percent: number): Promise<CourseAssignment> {
    const assignment = this.findAssignment(id);
    if (assignment.status === 'completed') throw new ApiError(409, 'Course is already completed');
    if (!Number.isInteger(percent) || percent < 0 || percent > 99) throw new ApiError(422, 'Прогресс должен быть от 0 до 99.');
    assignment.progress_percent = Math.max(assignment.progress_percent, percent);
    assignment.status = assignment.progress_percent ? 'in_progress' : 'not_started';
    return copy(assignment);
  }
  async completeCourse(id: string, answers: Record<string, number>): Promise<CourseAssignment> {
    const course = this.findCourse(id);
    const assignment = this.findAssignment(id);
    if (Object.keys(answers).length !== course.quiz.length || course.quiz.some(question => !Number.isInteger(answers[question.id]) || answers[question.id] < 0 || answers[question.id] >= question.options.length)) throw new ApiError(422, 'Answer every quiz question exactly once');
    const correct = course.quiz.filter(question => answers[question.id] === course.correctAnswers[question.id]).length;
    assignment.status = 'completed';
    assignment.progress_percent = 100;
    assignment.score_percent = Math.round(correct / course.quiz.length * 10000) / 100;
    assignment.completed_at = now();
    if (this.actor.manager_id) this.notify('Обучение завершено', `${this.actor.full_name} завершил(а) курс «${course.title}».`, 'course_completed', null, this.actor.manager_id);
    return copy(assignment);
  }
  async askJana(question: string): Promise<JanaAnswer> {
    if (question.trim().length < 3 || question.length > 2000) throw new ApiError(422, 'Напишите вопрос длиной от 3 до 2000 символов.');
    const query = question.toLowerCase();
    let answer = '';
    let source = '';
    if (/отпуск|отдых|vacation|leave/.test(query)) {
      answer = 'Чтобы оформить отпуск, откройте «Мои заявки», нажмите «Создать заявку» и выберите «Отпуск». Укажите даты начала и окончания, при необходимости добавьте комментарий и отправьте заявку.\n\nРешение руководителя и историю изменений можно посмотреть в карточке заявки. Остаток отпускных дней указан в вашем профиле.';
      source = 'Демо: порядок оформления отпуска';
    } else if (/аванс|выплат|advance/.test(query)) {
      answer = 'Чтобы запросить аванс, создайте новую заявку типа «Аванс», укажите сумму и отправьте на согласование. Статус и комментарий руководителя появятся в карточке заявки. Решение принимает ваш руководитель или HR.';
      source = 'Демо: порядок оформления аванса';
    } else if (/заявк|статус/.test(query)) {
      answer = 'Статус обращения можно посмотреть в разделе «Мои заявки». Нажмите на заявку, чтобы открыть её параметры, историю согласования и комментарий руководителя или HR. Когда решение будет принято, оно также появится в уведомлениях.';
      source = 'Демо: руководство по работе с заявками';
    } else if (/обуч|курс|academy|учеб/.test(query)) {
      answer = 'Назначенные вам курсы доступны в Jana Academy. Откройте курс, изучите материал и ответьте на вопросы теста. После отправки ответов появится результат, а курс будет отмечен как завершённый. Новые курсы назначает руководитель или HR.';
      source = 'Демо: руководство по Jana Academy';
    } else if (/профил|данн|доступ|роль/.test(query)) {
      answer = 'Ваши кадровые сведения доступны в разделе «Мой профиль». Они доступны только для чтения. Если заметили ошибку, обратитесь в HR. Сотрудник видит собственные данные, руководитель — данные своей команды.';
      source = 'Демо: политика доступа к кадровым данным';
    }
    return { answer: answer || 'В демонстрационной базе Jana нет подтверждённой информации по этому вопросу. Обратитесь в HR. Я могу подсказать, как оформить отпуск или аванс, пройти обучение и посмотреть профиль.', sources: source ? [{ title: source, url: null }] : [], grounded: Boolean(source), escalation_suggested: !source };
  }
}

export function createDemoApi(role: AppRole = 'worker'): DemoApi { return new DemoApi(role); }
