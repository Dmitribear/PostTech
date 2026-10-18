alter table public.courses
    add column course_type text not null default 'internal' check (course_type in ('internal','external')),
    add column provider text not null default '',
    add column external_url text,
    add constraint external_course_link check (course_type <> 'external' or
        (external_url is not null and length(btrim(provider)) between 1 and 160 and length(external_url) <= 2000
         and external_url ~ '^https://[^/@[:space:]]+([/?#][^[:space:]]*)?$'));

create table public.course_progress_events (
    id uuid primary key default gen_random_uuid(),
    assignment_id uuid not null references public.course_assignments(id) on delete cascade,
    actor_id uuid not null references public.employee_profiles(id),
    previous_percent integer not null,
    progress_percent integer not null check(progress_percent between 0 and 100),
    created_at timestamptz not null default now()
);
create index course_progress_events_assignment_idx on public.course_progress_events(assignment_id,created_at desc);
alter table public.course_progress_events enable row level security;
revoke all on public.course_progress_events from anon,authenticated;
grant all on public.course_progress_events to service_role;

alter function public.edit_academy_course(uuid,uuid,text,integer,jsonb) rename to edit_academy_course_v18;
create function public.edit_academy_course(p_actor_id uuid,p_id uuid,p_action text,p_revision integer,p_data jsonb)
returns jsonb language plpgsql security invoker set search_path=public,pg_temp as $$
declare c courses; family uuid; next_version integer; kind text;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then
  raise exception using errcode='PT403',message='HR role required'; end if;
 perform pg_advisory_xact_lock(81008);
 select * into c from courses where id=p_id for update;
 kind:=case when p_action in ('create','save') then coalesce(p_data->>'course_type','internal') else c.course_type end;
 if c.id is not null and p_action='create' then return to_jsonb(c); end if;
 if c.id is not null and kind is distinct from c.course_type then
  raise exception using errcode='PT409',message='Create a new course to change its format'; end if;
 if kind='internal' then return edit_academy_course_v18(p_actor_id,p_id,p_action,p_revision,p_data); end if;
 if kind is distinct from 'external' then raise exception using errcode='PT422',message='Invalid course format'; end if;
 if p_action in ('create','save') then
  if coalesce(p_data->>'external_url','') !~ '^https://[^/@[:space:]]+([/?#][^[:space:]]*)?$'
     or length(coalesce(p_data->>'external_url',''))>2000
     or length(btrim(coalesce(p_data->>'provider',''))) not between 1 and 160
     or length(btrim(coalesce(p_data->>'title',''))) not between 3 and 200
     or coalesce((p_data->>'duration_minutes')::int,-1) not between 0 and 525600
     or coalesce(p_data->'quiz','[]') <> '[]'::jsonb or coalesce(p_data->'lessons','[]') <> '[]'::jsonb then
   raise exception using errcode='PT422',message='External course needs title, provider, HTTPS link and duration'; end if;
 end if;
 if p_action='create' then
  family:=coalesce((p_data->>'family_id')::uuid,p_id);
  if family<>p_id and not exists(select 1 from courses where family_id=family) then
   raise exception using errcode='PT404',message='Course family not found'; end if;
  select coalesce(max(version),0)+1 into next_version from courses where family_id=family;
  insert into courses(id,title,description,duration_minutes,material_markdown,quiz,active,category,audience,passing_score,
      publication_state,family_id,version,translations,course_type,provider,external_url)
  values(p_id,p_data->>'title',coalesce(p_data->>'description',''),(p_data->>'duration_minutes')::int,'','[]',false,
      p_data->>'category',p_data->>'audience',80,'draft',family,next_version,coalesce(p_data->'translations','{}'),
      'external',p_data->>'provider',p_data->>'external_url') returning * into c;
 else
  if c.id is null then raise exception using errcode='PT404',message='Course not found'; end if;
  if c.revision<>p_revision then raise exception using errcode='PT409',message='Course changed; reload before saving'; end if;
  if p_action in ('save','publish') and c.publication_state<>'draft' then
   raise exception using errcode='PT409',message='Published courses are immutable; create a new version'; end if;
  if p_action='save' then
   update courses set title=p_data->>'title',description=coalesce(p_data->>'description',''),duration_minutes=(p_data->>'duration_minutes')::int,
     provider=p_data->>'provider',external_url=p_data->>'external_url',category=p_data->>'category',audience=p_data->>'audience',
     translations=coalesce(p_data->'translations','{}'),revision=revision+1 where id=p_id returning * into c;
  elsif p_action='publish' then
   update courses set active=false,publication_state='archived',revision=revision+1 where family_id=c.family_id and publication_state='published';
   update courses set active=true,publication_state='published',revision=revision+1 where id=p_id returning * into c;
  elsif p_action='archive' then
   update courses set active=false,publication_state='archived',revision=revision+1 where id=p_id returning * into c;
  else raise exception using errcode='PT422',message='Unknown course action'; end if;
 end if;
 return to_jsonb(c);
end $$;

create function public.enroll_external_course(p_actor_id uuid,p_course_id uuid) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare a course_assignments;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id) then
  raise exception using errcode='PT403',message='Employee profile required'; end if;
 perform id from courses where id=p_course_id and course_type='external' and active and publication_state='published' for share;
 if not found then raise exception using errcode='PT404',message='Published external course not found'; end if;
 insert into course_assignments(employee_id,course_id,assigned_by) values(p_actor_id,p_course_id,p_actor_id)
 on conflict(employee_id,course_id) do nothing;
 select * into a from course_assignments where employee_id=p_actor_id and course_id=p_course_id;
 return to_jsonb(a);
end $$;

alter function public.update_academy_progress(uuid,uuid,integer) rename to update_academy_progress_v18;
create function public.update_academy_progress(p_actor_id uuid,p_course_id uuid,p_progress_percent integer) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare a course_assignments; c courses; e employee_profiles; previous integer;
begin
 select * into c from courses where id=p_course_id;
 if c.course_type is distinct from 'external' then return update_academy_progress_v18(p_actor_id,p_course_id,p_progress_percent); end if;
 if p_progress_percent is null or p_progress_percent not between 0 and 100 then
  raise exception using errcode='PT422',message='Progress must be between 0 and 100'; end if;
 select * into a from course_assignments where employee_id=p_actor_id and course_id=p_course_id for update;
 if not found then raise exception using errcode='PT404',message='Course assignment not found'; end if;
 if a.status='completed' or a.progress_percent>=p_progress_percent then return to_jsonb(a); end if;
 previous:=a.progress_percent;
 update course_assignments set progress_percent=p_progress_percent,
   status=case when p_progress_percent=100 then 'completed'::course_status else 'in_progress'::course_status end,
   score_percent=null,completed_at=case when p_progress_percent=100 then now() else null end
 where id=a.id returning * into a;
 insert into course_progress_events(assignment_id,actor_id,previous_percent,progress_percent) values(a.id,p_actor_id,previous,p_progress_percent);
 if p_progress_percent=100 then
  select * into e from employee_profiles where id=p_actor_id;
  insert into notifications(employee_id,course_id,notification_type,title,body)
  values(p_actor_id,p_course_id,'course_completed','Курс отмечен пройденным',format('Вы отметили завершение курса «%s» (%s).',c.title,c.provider));
  insert into notifications(employee_id,course_id,notification_type,title,body)
  select id,p_course_id,'team_course_completed','Сотрудник отметил завершение курса',
    format('%s отметил(а) завершение курса «%s» (%s). Прогресс указан сотрудником.',e.full_name,c.title,c.provider)
  from employee_profiles where id=e.manager_id and id<>p_actor_id and role in ('manager','director','hr_admin');
 end if;
 return to_jsonb(a);
end $$;

do $$ declare f record; begin
 for f in select oid::regprocedure signature from pg_proc where pronamespace='public'::regnamespace
 and proname in ('edit_academy_course','enroll_external_course','update_academy_progress') loop
  execute format('revoke execute on function %s from public,anon,authenticated',f.signature);
  execute format('grant execute on function %s to service_role',f.signature);
 end loop;
end $$;
