-- Demo content. Run the migration first.
-- Apply the complete database/migration-plan.json before this local demo seed.
-- Create these four Supabase Auth users before running
-- this seed so employee profile IDs can reference real auth.users rows:
--   hr@posttech.demo
--   director@posttech.demo
--   manager@posttech.demo
--   employee@posttech.demo

insert into public.courses (id, title, description, duration_minutes, material_markdown, quiz)
values
(
    '10000000-0000-4000-8000-000000000001',
    'Добро пожаловать в JanaMen',
    'Краткий курс по внутренним HR-сервисам и правилам работы с заявками.',
    15,
    E'# Добро пожаловать\n\nПрофиль показывает ваши кадровые данные, назначенное обучение и уведомления.\n\nДля отпуска создайте заявку с датами. Для аванса укажите сумму. Статус заявки можно отслеживать в разделе «Мои заявки».\n\nОфициальные кадровые сведения в прототипе доступны только для чтения.',
    '[{"id":"intro-1","prompt":"Где посмотреть статус заявки?","options":["В разделе «Мои заявки»","В настройках браузера","Только по почте"],"answer_index":0},{"id":"intro-2","prompt":"Можно ли редактировать официальные кадровые сведения?","options":["Да, любой пользователь","Нет, они доступны только для чтения","Только через Jana Academy"],"answer_index":1}]'::jsonb
),
(
    '10000000-0000-4000-8000-000000000002',
    'Безопасность персональных данных',
    'Основные правила доступа к кадровой информации.',
    20,
    E'# Безопасность данных\n\nСотрудник видит только собственный профиль и собственные заявки. Руководитель видит данные только своей команды. HR/администратор имеет доступ к кадровым данным в рамках своей роли.\n\nНе отправляйте пароли, токены и персональные сведения в AI Jana. AI Jana отвечает только на основе опубликованной базы знаний.',
    '[{"id":"privacy-1","prompt":"Какие данные доступны руководителю?","options":["Данные всей компании","Данные своей команды","Только свои данные"],"answer_index":1},{"id":"privacy-2","prompt":"Что должна сделать Jana, если в базе нет ответа?","options":["Угадать ответ","Сообщить, что данных недостаточно, и направить в HR","Показать чужой профиль"],"answer_index":1}]'::jsonb
)
on conflict (id) do update set
    title = excluded.title,
    description = excluded.description,
    duration_minutes = excluded.duration_minutes,
    material_markdown = excluded.material_markdown,
    quiz = excluded.quiz,
    active = true;

-- Load the current, reviewed Jana demo articles separately from
-- database/seed_jana_demo.sql. Keeping one knowledge seed avoids stale duplicates.

insert into public.employee_profiles (
    auth_user_id, employee_code, full_name, email, company, job_title,
    department, hired_at, vacation_days_remaining, role, external_source
)
select u.id, 'DEMO-HR-001', 'Демо HR-администратор', u.email,
       'PostTech', 'HR-администратор', 'HR', current_date - 800, 28, 'hr_admin', 'mock-1c-zup'
from auth.users u where u.email = 'hr@posttech.demo'
on conflict (auth_user_id) do update set role = excluded.role, full_name = excluded.full_name;

insert into public.employee_profiles (
    auth_user_id, employee_code, full_name, email, company, job_title,
    department, hired_at, vacation_days_remaining, role, external_source
)
select u.id, 'DEMO-DIR-001', 'Демо директор', u.email,
       'PostTech', 'Директор', 'Руководство', current_date - 1800, 28, 'director', 'mock-1c-zup'
from auth.users u where u.email = 'director@posttech.demo'
on conflict (auth_user_id) do update set role = excluded.role, full_name = excluded.full_name;

insert into public.employee_profiles (
    auth_user_id, employee_code, full_name, email, company, job_title,
    department, manager_id, hired_at, vacation_days_remaining, role, external_source
)
select u.id, 'DEMO-MGR-001', 'Демо руководитель', u.email,
       'PostTech', 'Руководитель отдела', 'Разработка', director.id,
       current_date - 1200, 24, 'manager', 'mock-1c-zup'
from auth.users u
cross join public.employee_profiles director
where u.email = 'manager@posttech.demo'
  and director.email = 'director@posttech.demo'
on conflict (auth_user_id) do update set
    role = excluded.role,
    manager_id = excluded.manager_id,
    full_name = excluded.full_name;

insert into public.employee_profiles (
    auth_user_id, employee_code, full_name, email, company, job_title,
    department, manager_id, hired_at, vacation_days_remaining, role, external_source
)
select u.id, 'DEMO-EMP-001', 'Демо сотрудник', u.email,
       'PostTech', 'Разработчик', 'Разработка', manager_profile.id,
       current_date - 400, 18, 'worker', 'mock-1c-zup'
from auth.users u
cross join public.employee_profiles manager_profile
where u.email = 'employee@posttech.demo'
  and manager_profile.email = 'manager@posttech.demo'
on conflict (auth_user_id) do update set
    role = excluded.role,
    manager_id = excluded.manager_id,
    full_name = excluded.full_name;

insert into public.course_assignments (course_id, employee_id, assigned_by)
select c.id, employee.id, hr.id
from public.courses c
cross join public.employee_profiles employee
cross join public.employee_profiles hr
where c.id in (
    '10000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000002'
)
  and employee.email = 'employee@posttech.demo'
  and hr.email = 'hr@posttech.demo'
on conflict (course_id, employee_id) do nothing;

-- Exercise the same transactional flow as the API. Rerunning the seed never
-- overwrites existing decisions or repeats an approval/notification.
do $$
declare employee uuid; manager uuid; hr uuid; request jsonb;
begin
 select id into employee from public.employee_profiles where email='employee@posttech.demo';
 select id into manager from public.employee_profiles where email='manager@posttech.demo';
 select id into hr from public.employee_profiles where email='hr@posttech.demo';
 if employee is not null and manager is not null and hr is not null then
  if not exists(select 1 from public.hr_requests where employee_id=employee and comment like 'Демо-заявка на отпуск:%') then
   perform public.create_hr_request(employee,'leave',current_date+14,current_date+18,null,
    'Демо-заявка на отпуск: ожидает решения руководителя.','40000000-0000-4000-8000-000000000001');
  end if;
  if not exists(select 1 from public.hr_requests where employee_id=employee and comment like 'Демо-заявка на аванс:%') then
   request:=public.create_hr_request(employee,'advance',null,null,50000,
    'Демо-заявка на аванс: одобрена.','40000000-0000-4000-8000-000000000002');
   perform public.review_hr_request(manager,(request->>'id')::uuid,'approved','Демо: согласовано руководителем');
   perform public.review_hr_request(hr,(request->>'id')::uuid,'approved','Демо: окончательно одобрено HR');
  end if;
 end if;
end $$;

insert into public.notifications (employee_id, notification_type, title, body)
select employee.id, 'training_assigned', 'Назначено обучение', 'Вам назначены два вводных курса Jana Academy.'
from public.employee_profiles employee
where employee.email = 'employee@posttech.demo'
 and not exists(select 1 from public.notifications n where n.employee_id=employee.id and n.notification_type='training_assigned');
