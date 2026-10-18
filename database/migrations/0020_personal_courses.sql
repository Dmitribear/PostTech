alter table public.courses
    add column owner_employee_id uuid references public.employee_profiles(id),
    add column personal_creation_payload jsonb,
    add constraint personal_course_external check (owner_employee_id is null or course_type = 'external');
create index courses_owner_idx on public.courses(owner_employee_id) where owner_employee_id is not null;

create function public.guard_personal_course_assignment() returns trigger
language plpgsql set search_path=public,pg_temp as $$
begin
 if exists(select 1 from courses where id=new.course_id and owner_employee_id is not null and owner_employee_id<>new.employee_id) then
  raise exception using errcode='PT403',message='Personal course belongs to another employee';
 end if;
 return new;
end $$;
create trigger personal_course_assignment before insert or update of course_id,employee_id
on public.course_assignments for each row execute function public.guard_personal_course_assignment();

create function public.create_personal_course(p_actor_id uuid,p_id uuid,p_data jsonb) returns jsonb
language plpgsql security invoker set search_path=public,pg_temp as $$
declare c courses; a course_assignments; progress integer;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id) then
  raise exception using errcode='PT403',message='Employee profile required'; end if;
 if p_id is null or p_data is null then raise exception using errcode='PT422',message='Course data required'; end if;
 perform pg_advisory_xact_lock(hashtextextended(p_id::text,20));
 select * into c from courses where id=p_id;
 if found then
  if c.owner_employee_id is distinct from p_actor_id or c.personal_creation_payload is distinct from p_data then
   raise exception using errcode='PT409',message='Operation key already used'; end if;
  select * into a from course_assignments where course_id=p_id and employee_id=p_actor_id;
  return to_jsonb(a);
 end if;
 if length(btrim(coalesce(p_data->>'title',''))) not between 3 and 200
    or length(btrim(coalesce(p_data->>'provider',''))) not between 1 and 160
    or coalesce(p_data->>'external_url','') !~ '^https://[^/@[:space:]]+([/?#][^[:space:]]*)?$'
    or length(p_data->>'external_url')>2000
    or coalesce(p_data->>'progress_percent','') !~ '^(100|[0-9]{1,2})$'
    or coalesce(p_data->>'due_on','') !~ '^\d{4}-\d{2}-\d{2}$' then
  raise exception using errcode='PT422',message='Invalid personal course'; end if;
 progress:=(p_data->>'progress_percent')::integer;
 insert into courses(id,title,description,duration_minutes,material_markdown,quiz,active,category,audience,
   passing_score,publication_state,family_id,version,course_type,provider,external_url,owner_employee_id,personal_creation_payload)
 values(p_id,btrim(p_data->>'title'),' ',0,'','[]',true,'Повышение квалификации','Индивидуальное обучение',
   80,'published',p_id,1,'external',btrim(p_data->>'provider'),p_data->>'external_url',p_actor_id,p_data);
 insert into course_assignments(course_id,employee_id,assigned_by,due_on)
 values(p_id,p_actor_id,p_actor_id,(p_data->>'due_on')::date) returning * into a;
 if progress>0 then return update_academy_progress(p_actor_id,p_id,progress); end if;
 return to_jsonb(a);
end $$;
revoke execute on function public.create_personal_course(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.create_personal_course(uuid,uuid,jsonb) to service_role;
revoke execute on function public.guard_personal_course_assignment() from public,anon,authenticated;
notify pgrst,'reload schema';
