begin;

-- Raw invitation codes never enter the database. Only server-side SHA-256
-- hashes are stored. Every command is service-role-only and checks its actor.
create table public.registration_invitations (
    id uuid primary key default gen_random_uuid(),
    token_hash text not null unique check (token_hash ~ '^[a-f0-9]{64}$'),
    email text not null check (email = lower(btrim(email)) and email ~ '^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$'),
    employee_code text not null check (length(btrim(employee_code)) between 1 and 80),
    company text not null check (length(btrim(company)) between 1 and 120),
    job_title text not null check (length(btrim(job_title)) between 1 and 160),
    department text not null check (length(btrim(department)) between 1 and 160),
    hired_at date not null,
    manager_id uuid references public.employee_profiles(id) on delete restrict,
    role public.app_role not null default 'worker',
    vacation_days_remaining numeric(5,1) not null default 0 check (vacation_days_remaining >= 0),
    first_name text,
    last_name text,
    created_by uuid not null references public.employee_profiles(id) on delete restrict,
    created_at timestamptz not null default now(),
    expires_at timestamptz not null,
    revoked_at timestamptz,
    last_sent_at timestamptz,
    consumed_at timestamptz,
    consumed_by uuid references auth.users(id) on delete restrict,
    profile_id uuid references public.employee_profiles(id) on delete restrict,
    check (expires_at > created_at),
    check ((consumed_at is null and consumed_by is null and profile_id is null)
        or (consumed_at is not null and consumed_by is not null and profile_id is not null))
);
create unique index registration_invitation_active_email_idx on public.registration_invitations(email)
    where consumed_at is null and revoked_at is null;
create unique index registration_invitation_active_employee_idx on public.registration_invitations(employee_code)
    where consumed_at is null and revoked_at is null;
alter table public.registration_invitations enable row level security;
revoke all on public.registration_invitations from public, anon, authenticated;

create function public.issue_registration_invitation(p_actor_id uuid, p_token_hash text, p_details jsonb)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_invite public.registration_invitations;
    v_email text := lower(btrim(p_details->>'email'));
    v_manager uuid := (p_details->>'manager_id')::uuid;
    v_hours integer := coalesce((p_details->>'expires_in_hours')::integer,72);
begin
    if not exists (select 1 from public.employee_profiles where id = p_actor_id and role = 'hr_admin') then
        raise exception using errcode='PT403', message='HR administrator role required';
    end if;
    if v_hours < 1 or v_hours > 168 then
        raise exception using errcode='PT422', message='Invitation lifetime must be between 1 and 168 hours';
    end if;
    if v_manager is not null then
        perform id from public.employee_profiles where id=v_manager and role in ('manager','hr_admin') for share;
        if not found then raise exception using errcode='PT422', message='Invitation manager must be a manager or HR administrator'; end if;
    end if;
    perform pg_advisory_xact_lock(hashtextextended(v_email,71224));
    if exists(select 1 from public.employee_profiles where lower(email)=v_email or employee_code=p_details->>'employee_code') then
        raise exception using errcode='PT409', message='An employee profile already exists for this email or employee code';
    end if;
    update public.registration_invitations set revoked_at=now()
    where consumed_at is null and revoked_at is null and expires_at <= now()
      and (email=v_email or employee_code=p_details->>'employee_code');
    if exists(select 1 from public.registration_invitations where consumed_at is null and revoked_at is null
        and (email=v_email or employee_code=p_details->>'employee_code')) then
        raise exception using errcode='PT409', message='An active invitation already exists for this employee';
    end if;
    insert into public.registration_invitations(token_hash,email,employee_code,company,job_title,department,
        hired_at,manager_id,role,vacation_days_remaining,created_by,expires_at)
    values(p_token_hash,v_email,p_details->>'employee_code',p_details->>'company',p_details->>'job_title',
        p_details->>'department',(p_details->>'hired_at')::date,v_manager,
        coalesce((p_details->>'role')::public.app_role,'worker'),
        coalesce((p_details->>'vacation_days_remaining')::numeric,0),p_actor_id,now()+make_interval(hours=>v_hours))
    returning * into v_invite;
    return jsonb_build_object('id',v_invite.id,'email',v_invite.email,'role',v_invite.role,
        'department',v_invite.department,'expires_at',v_invite.expires_at);
exception when unique_violation then
    raise exception using errcode='PT409', message='An active invitation already exists for this employee';
end;
$$;

create function public.check_registration_invitation(p_token_hash text, p_allow_consumed boolean default false)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_invite public.registration_invitations;
begin
    select * into v_invite from public.registration_invitations where token_hash=p_token_hash;
    if not found then raise exception using errcode='PT404', message='Invitation code is invalid'; end if;
    if v_invite.consumed_at is not null then
        if not p_allow_consumed then raise exception using errcode='PT409', message='Invitation has already been used. Sign in to your account'; end if;
    elsif v_invite.revoked_at is not null or v_invite.expires_at <= clock_timestamp() then
        raise exception using errcode='PT410', message='Invitation has expired or was revoked. Contact HR for a new code';
    end if;
    return jsonb_build_object('email',v_invite.email,'role',v_invite.role,
        'department',v_invite.department,'expires_at',v_invite.expires_at);
end;
$$;

create function public.prepare_registration_invitation(p_token_hash text, p_first_name text default null,
    p_last_name text default null, p_resend boolean default false)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_invite public.registration_invitations;
begin
    select * into v_invite from public.registration_invitations where token_hash=p_token_hash for update;
    perform public.check_registration_invitation(p_token_hash,false);
    if v_invite.last_sent_at is not null and v_invite.last_sent_at > now()-interval '60 seconds' then
        raise exception using errcode='PT429', message='Please wait 60 seconds before requesting another email';
    end if;
    if p_resend then
        if v_invite.first_name is null then raise exception using errcode='PT409', message='Create your account before requesting a confirmation email'; end if;
    else
        if p_first_name is null or p_last_name is null or length(btrim(p_first_name)) not between 1 and 80
            or length(btrim(p_last_name)) not between 1 and 80 then
            raise exception using errcode='PT422', message='Enter your first and last name';
        end if;
        v_invite.first_name := btrim(p_first_name);
        v_invite.last_name := btrim(p_last_name);
    end if;
    update public.registration_invitations set first_name=v_invite.first_name,last_name=v_invite.last_name,last_sent_at=now()
        where id=v_invite.id;
    return jsonb_build_object('email',v_invite.email);
end;
$$;

create function public.complete_registration_invitation(p_token_hash text, p_auth_user_id uuid,
    p_first_name text default null,p_last_name text default null)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
    v_invite public.registration_invitations;
    v_email text;
    v_confirmed timestamptz;
    v_profile public.employee_profiles;
begin
    select * into v_invite from public.registration_invitations where token_hash=p_token_hash for update;
    if not found then raise exception using errcode='PT404', message='Invitation code is invalid'; end if;
    -- Never trust the sign-up response, user metadata, or browser claims. Check
    -- authoritative Auth state again within the profile-creation transaction.
    select lower(email),email_confirmed_at into v_email,v_confirmed from auth.users where id=p_auth_user_id for share;
    if v_confirmed is null or v_email is distinct from v_invite.email then
        raise exception using errcode='PT403', message='Confirm the invited email before activating your workspace';
    end if;
    if v_invite.consumed_at is not null then
        if v_invite.consumed_by is distinct from p_auth_user_id then
            raise exception using errcode='PT409', message='Invitation has already been used';
        end if;
        return jsonb_build_object('profile_id',v_invite.profile_id,'role',v_invite.role);
    end if;
    perform public.check_registration_invitation(p_token_hash,false);
    if v_invite.first_name is null or v_invite.last_name is null then
        if p_first_name is null or p_last_name is null or length(btrim(p_first_name)) not between 1 and 80
            or length(btrim(p_last_name)) not between 1 and 80 then
            raise exception using errcode='PT422', message='Enter your first and last name to activate your workspace';
        end if;
        v_invite.first_name := btrim(p_first_name);
        v_invite.last_name := btrim(p_last_name);
    end if;
    if v_invite.manager_id is not null then
        perform id from public.employee_profiles where id=v_invite.manager_id
            and auth_user_id<>p_auth_user_id and role in ('manager','hr_admin') for share;
        if not found then raise exception using errcode='PT409', message='Your reporting manager has changed. Contact HR'; end if;
    end if;
    -- A second invitation cannot alter an existing account's role or balance.
    if exists(select 1 from public.employee_profiles where auth_user_id=p_auth_user_id
        or lower(email)=v_email or employee_code=v_invite.employee_code) then
        raise exception using errcode='PT409', message='An employee profile already exists. Contact HR';
    end if;
    insert into public.employee_profiles(auth_user_id,employee_code,full_name,email,company,job_title,department,
        manager_id,hired_at,vacation_days_remaining,role,external_source)
    values(p_auth_user_id,v_invite.employee_code,v_invite.first_name||' '||v_invite.last_name,v_invite.email,
        v_invite.company,v_invite.job_title,v_invite.department,v_invite.manager_id,v_invite.hired_at,
        v_invite.vacation_days_remaining,v_invite.role,'hr-invitation') returning * into v_profile;
    update public.registration_invitations set consumed_at=now(),consumed_by=p_auth_user_id,profile_id=v_profile.id,
        first_name=v_invite.first_name,last_name=v_invite.last_name
        where id=v_invite.id;
    return jsonb_build_object('profile_id',v_profile.id,'role',v_profile.role);
exception when unique_violation then
    raise exception using errcode='PT409', message='An employee profile already exists. Contact HR';
end;
$$;

create function public.revoke_registration_invitation(p_actor_id uuid,p_invitation_id uuid)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v_invite public.registration_invitations;
begin
    if not exists(select 1 from public.employee_profiles where id=p_actor_id and role='hr_admin') then
        raise exception using errcode='PT403',message='HR administrator role required';
    end if;
    select * into v_invite from public.registration_invitations where id=p_invitation_id for update;
    if not found then raise exception using errcode='PT404',message='Invitation not found'; end if;
    if v_invite.consumed_at is not null then raise exception using errcode='PT409',message='Invitation has already been used'; end if;
    update public.registration_invitations set revoked_at=coalesce(revoked_at,now()) where id=p_invitation_id;
    return jsonb_build_object('id',p_invitation_id,'revoked',true);
end;
$$;

create function public.list_registration_invitations(p_actor_id uuid)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if not exists(select 1 from public.employee_profiles where id=p_actor_id and role='hr_admin') then
        raise exception using errcode='PT403',message='HR administrator role required';
    end if;
    return coalesce((select jsonb_agg(item order by created_at desc) from (
        select created_at,jsonb_build_object('id',id,'email',email,'role',role,'department',department,
            'employee_code',employee_code,'expires_at',expires_at,'created_at',created_at,
            'revoked_at',revoked_at,'consumed_at',consumed_at) as item
        from public.registration_invitations order by created_at desc limit 200
    ) recent),'[]'::jsonb);
end;
$$;

revoke execute on function public.issue_registration_invitation(uuid,text,jsonb),
    public.check_registration_invitation(text,boolean), public.prepare_registration_invitation(text,text,text,boolean),
    public.complete_registration_invitation(text,uuid,text,text),public.revoke_registration_invitation(uuid,uuid),
    public.list_registration_invitations(uuid)
    from public,anon,authenticated;
grant execute on function public.issue_registration_invitation(uuid,text,jsonb),
    public.check_registration_invitation(text,boolean), public.prepare_registration_invitation(text,text,text,boolean),
    public.complete_registration_invitation(text,uuid,text,text),public.revoke_registration_invitation(uuid,uuid),
    public.list_registration_invitations(uuid) to service_role;
notify pgrst, 'reload schema';
commit;
