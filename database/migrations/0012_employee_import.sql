begin;
create table public.employee_imports (
 id uuid primary key default gen_random_uuid(), created_by uuid not null references public.employee_profiles(id),
 filename text not null, rows jsonb not null, errors jsonb not null, created_at timestamptz not null default now(),
 expires_at timestamptz not null default now()+interval '1 hour', applied_at timestamptz, result jsonb
);
alter table public.employee_imports enable row level security;
revoke all on public.employee_imports from public,anon,authenticated;
grant all on public.employee_imports to service_role;
grant select(id,email,employee_code,consumed_at,revoked_at,expires_at) on public.registration_invitations to service_role;

create function public.apply_employee_import(p_actor_id uuid,p_id uuid,p_hashes jsonb) returns jsonb
language plpgsql security definer set search_path=public,pg_temp as $$
declare batch employee_imports; item jsonb; profile employee_profiles; invitation jsonb; invites jsonb:='[]'; updates integer:=0;
begin
 if not exists(select 1 from employee_profiles where id=p_actor_id and role='hr_admin') then raise exception using errcode='PT403',message='HR role required'; end if;
 select * into batch from employee_imports where id=p_id and created_by=p_actor_id for update;
 if not found then raise exception using errcode='PT404',message='Предпросмотр не найден'; end if;
 if batch.applied_at is not null then return batch.result||jsonb_build_object('already_applied',true); end if;
 if batch.expires_at<=now() then raise exception using errcode='PT409',message='Предпросмотр устарел. Загрузите файл заново'; end if;
 if jsonb_array_length(batch.errors)>0 then raise exception using errcode='PT422',message='Сначала исправьте ошибки файла'; end if;
 -- Stable lock order, no partial updates when a profile or invitation changes.
 lock table employee_profiles in share row exclusive mode;
 lock table registration_invitations in share row exclusive mode;
 for item in select value from jsonb_array_elements(batch.rows) loop
  if item->>'action' in ('update','unchanged') then
   select * into profile from employee_profiles where id=(item->>'profile_id')::uuid;
   if not found or profile.updated_at is distinct from (item->>'expected_updated_at')::timestamptz or lower(profile.email)<>item->>'email' or profile.employee_code<>item->>'employee_code' then
    raise exception using errcode='PT409',message='Данные сотрудника изменились. Повторите предпросмотр'; end if;
   if item->>'action'='update' then
    -- Imports do not change access, reporting structure, email or leave balances.
    update employee_profiles set full_name=item->>'full_name',company=item->>'company',job_title=item->>'job_title',department=item->>'department',hired_at=(item->>'hired_at')::date,updated_at=now() where id=profile.id;
    updates:=updates+1;
   end if;
  elsif item->>'action'='invite' then
   if item->>'role' not in ('worker','manager') or item->>'role' is null then
    raise exception using errcode='PT422',message='Доступ HR и директора выдаётся отдельным приглашением, а не массовым импортом';
   end if;
   invitation:=issue_registration_invitation(p_actor_id,p_hashes->>(item->>'employee_code'),item||jsonb_build_object('expires_in_hours',168));
   invites:=invites||jsonb_build_array(invitation||jsonb_build_object('employee_code',item->>'employee_code'));
  else raise exception using errcode='PT422',message='Некорректная строка импорта';
  end if;
 end loop;
 update employee_imports set applied_at=now(),result=jsonb_build_object('updated',updates,'invitations',invites) where id=p_id returning * into batch;
 return batch.result;
end $$;
revoke all on function public.apply_employee_import(uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.apply_employee_import(uuid,uuid,jsonb) to service_role;
notify pgrst,'reload schema';
commit;
