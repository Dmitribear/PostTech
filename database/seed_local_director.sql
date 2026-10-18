-- Only the isolated Docker bootstrap may create this demonstration profile.
do $$ begin
  if current_setting('posttech.local_container', true) is distinct from 'on' then
    raise exception 'Local Docker bootstrap required';
  end if;
end $$;

insert into public.employee_profiles (
  auth_user_id, employee_code, full_name, email, company, job_title,
  department, hired_at, vacation_days_remaining, role, external_source
)
select u.id, 'DEMO-DIR-001', 'Демо директор', u.email,
  'PostTech', 'Директор', 'Руководство', current_date - 1500, 28, 'director', 'mock-1c-zup'
from auth.users u where u.email = 'director@posttech.demo'
on conflict (auth_user_id) do nothing;

update public.employee_profiles manager
set manager_id = director.id
from public.employee_profiles director
where manager.email = 'manager@posttech.demo'
  and director.email = 'director@posttech.demo'
  and manager.manager_id is null;
