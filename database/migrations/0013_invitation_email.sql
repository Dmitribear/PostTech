begin;

alter table public.registration_invitations
    add column email_status text not null default 'not_sent'
        check (email_status in ('not_sent','sending','accepted','failed','unknown')),
    add column email_attempted_at timestamptz,
    add column email_accepted_at timestamptz;

-- This is separate from last_sent_at, which throttles Auth confirmation codes.
create function public.begin_invitation_email(p_actor_id uuid, p_invitation_id uuid, p_token_hash text)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare v public.registration_invitations;
begin
    if not exists(select 1 from public.employee_profiles where id=p_actor_id and role='hr_admin') then
        raise exception using errcode='PT403',message='HR administrator role required';
    end if;
    select * into v from public.registration_invitations where id=p_invitation_id for update;
    if not found then raise exception using errcode='PT404',message='Invitation not found'; end if;
    if v.consumed_at is not null then raise exception using errcode='PT409',message='Invitation has already been used'; end if;
    if v.revoked_at is not null or v.expires_at<=now() then
        raise exception using errcode='PT410',message='Invitation has expired or was revoked. Contact HR for a new code';
    end if;
    if v.email_attempted_at > now()-interval '60 seconds' then
        raise exception using errcode='PT429',message='Please wait 60 seconds before requesting another email';
    end if;
    update public.registration_invitations set token_hash=p_token_hash,email_status='sending',
        email_attempted_at=now(),email_accepted_at=null where id=v.id;
    return jsonb_build_object('id',v.id,'email',v.email,'role',v.role,'department',v.department,'expires_at',v.expires_at);
end;
$$;

create function public.finish_invitation_email(p_invitation_id uuid,p_token_hash text,p_status text)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if p_status not in ('accepted','failed','unknown') then
        raise exception using errcode='PT422',message='Invalid email status';
    end if;
    -- An older, slower provider response must not overwrite a newer attempt.
    update public.registration_invitations set email_status=p_status,
        email_accepted_at=case when p_status='accepted' then now() else null end
        where id=p_invitation_id and token_hash=p_token_hash;
    return jsonb_build_object('recorded',found);
end;
$$;

create or replace function public.list_registration_invitations(p_actor_id uuid)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
begin
    if not exists(select 1 from public.employee_profiles where id=p_actor_id and role='hr_admin') then
        raise exception using errcode='PT403',message='HR administrator role required';
    end if;
    return coalesce((select jsonb_agg(item order by created_at desc) from (
        select created_at,jsonb_build_object('id',id,'email',email,'role',role,'department',department,
            'employee_code',employee_code,'expires_at',expires_at,'created_at',created_at,
            'revoked_at',revoked_at,'consumed_at',consumed_at,'email_status',email_status,
            'email_attempted_at',email_attempted_at,'email_accepted_at',email_accepted_at) as item
        from public.registration_invitations order by created_at desc limit 200
    ) recent),'[]'::jsonb);
end;
$$;

revoke execute on function public.begin_invitation_email(uuid,uuid,text),
    public.finish_invitation_email(uuid,text,text) from public,anon,authenticated;
grant execute on function public.begin_invitation_email(uuid,uuid,text),
    public.finish_invitation_email(uuid,text,text) to service_role;
notify pgrst,'reload schema';
commit;
