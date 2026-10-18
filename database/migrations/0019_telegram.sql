begin;

-- One identity per employee, established only by a short-lived website code.
-- Tokens and Telegram credentials are never stored in these tables.
create table public.telegram_links (
    id uuid primary key default gen_random_uuid(),
    employee_id uuid not null unique references public.employee_profiles(id) on delete cascade,
    telegram_user_id bigint not null unique check (telegram_user_id > 0),
    chat_id bigint not null check (chat_id = telegram_user_id),
    username text check (username is null or username ~ '^[A-Za-z0-9_]{1,64}$'),
    notifications_enabled boolean not null default true,
    linked_at timestamptz not null default now()
);
create table public.telegram_link_codes (
    employee_id uuid primary key references public.employee_profiles(id) on delete cascade,
    code_hash text not null unique check (code_hash ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz not null,
    consumed_at timestamptz,
    created_at timestamptz not null default now()
);
create table public.telegram_outbox (
    id uuid primary key default gen_random_uuid(),
    link_id uuid not null references public.telegram_links(id) on delete cascade,
    notification_id uuid not null unique references public.notifications(id) on delete cascade,
    state text not null default 'pending' check (state in ('pending','sending','sent','blocked','cancelled')),
    attempts integer not null default 0 check (attempts >= 0),
    available_at timestamptz not null default now(),
    lease_token uuid,
    lease_until timestamptz,
    delivered_at timestamptz,
    created_at timestamptz not null default now()
);
create index telegram_outbox_pending_idx on public.telegram_outbox(available_at,created_at) where state in ('pending','sending');
create table public.telegram_worker_state (
    bot_id bigint primary key check (bot_id>0),
    update_offset bigint not null default 0 check (update_offset >= 0)
);

alter table public.telegram_links enable row level security;
alter table public.telegram_link_codes enable row level security;
alter table public.telegram_outbox enable row level security;
alter table public.telegram_worker_state enable row level security;
revoke all on public.telegram_links,public.telegram_link_codes,public.telegram_outbox,public.telegram_worker_state
    from public,anon,authenticated,service_role;

create function public.telegram_status(p_actor_id uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare v public.telegram_links;
begin
    if not exists(select 1 from employee_profiles where id=p_actor_id) then
        raise exception using errcode='PT403',message='User has no HR profile';
    end if;
    select * into v from telegram_links where employee_id=p_actor_id;
    return jsonb_build_object('linked',found,'link_id',v.id,'telegram_username',v.username,
        'notifications_enabled',coalesce(v.notifications_enabled,false));
end;
$$;

create function public.issue_telegram_link(p_actor_id uuid,p_code_hash text)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare expiry timestamptz:=now()+interval '10 minutes';
begin
    perform 1 from employee_profiles where id=p_actor_id for update;
    if not found then raise exception using errcode='PT403',message='User has no HR profile'; end if;
    if exists(select 1 from telegram_links where employee_id=p_actor_id) then
        raise exception using errcode='PT409',message='Telegram is already linked; unlink it first';
    end if;
    if p_code_hash is null or p_code_hash !~ '^[0-9a-f]{64}$' then
        raise exception using errcode='PT422',message='Invalid linking code';
    end if;
    insert into telegram_link_codes(employee_id,code_hash,expires_at)
        values(p_actor_id,p_code_hash,expiry)
        on conflict(employee_id) do update set code_hash=excluded.code_hash,
            expires_at=excluded.expires_at,created_at=now(),consumed_at=null;
    return jsonb_build_object('expires_at',expiry);
end;
$$;

create function public.consume_telegram_link(p_code_hash text,p_telegram_user_id bigint,p_chat_id bigint,p_username text)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare code public.telegram_link_codes; profile public.employee_profiles;
begin
    if p_telegram_user_id is null or p_telegram_user_id<=0 or p_chat_id is distinct from p_telegram_user_id then
        raise exception using errcode='PT422',message='Linking is only available in a private chat';
    end if;
    if p_username is not null and p_username !~ '^[A-Za-z0-9_]{1,64}$' then
        raise exception using errcode='PT422',message='Invalid Telegram username';
    end if;
    select * into code from telegram_link_codes where code_hash=p_code_hash;
    if not found then raise exception using errcode='PT410',message='Linking code has expired or was used'; end if;
    -- Same lock order as issue/unlink; serializes link rotation and consumption.
    select * into profile from employee_profiles where id=code.employee_id for update;
    if not found then raise exception using errcode='PT403',message='User has no HR profile'; end if;
    select * into code from telegram_link_codes where code_hash=p_code_hash for update;
    if not found or code.consumed_at is not null or code.expires_at<=now() then
        raise exception using errcode='PT410',message='Linking code has expired or was used';
    end if;
    if exists(select 1 from telegram_links where employee_id=code.employee_id or telegram_user_id=p_telegram_user_id) then
        raise exception using errcode='PT409',message='Telegram is already linked; unlink it first';
    end if;
    insert into telegram_links(employee_id,telegram_user_id,chat_id,username)
        values(code.employee_id,p_telegram_user_id,p_chat_id,p_username);
    update telegram_link_codes set consumed_at=now() where employee_id=code.employee_id;
    -- No SELECT/INSERT of historical notifications: only new events are queued.
    return jsonb_build_object('linked',true,'employee_id',profile.id,'full_name',profile.full_name,'role',profile.role);
exception when unique_violation then
    raise exception using errcode='PT409',message='Telegram is already linked; unlink it first';
end;
$$;

create function public.resolve_telegram_actor(p_telegram_user_id bigint)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb;
begin
    select jsonb_build_object('id',p.id,'auth_user_id',p.auth_user_id,'role',p.role,'manager_id',p.manager_id)
        into result from telegram_links t join employee_profiles p on p.id=t.employee_id
        where t.telegram_user_id=p_telegram_user_id;
    if result is null then raise exception using errcode='PT403',message='Telegram account is not linked'; end if;
    return result;
end;
$$;

create function public.unlink_telegram(p_actor_id uuid)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
begin
    perform 1 from employee_profiles where id=p_actor_id for update;
    if not found then raise exception using errcode='PT403',message='User has no HR profile'; end if;
    delete from telegram_link_codes where employee_id=p_actor_id;
    -- Cascades queued deliveries; old leases cannot be acknowledged or revived.
    delete from telegram_links where employee_id=p_actor_id;
    return jsonb_build_object('linked',false);
end;
$$;

create function public.set_telegram_settings(p_actor_id uuid,p_notifications_enabled boolean)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare link uuid;
begin
    if p_notifications_enabled is null then raise exception using errcode='PT422',message='Invalid notification setting'; end if;
    update telegram_links set notifications_enabled=p_notifications_enabled where employee_id=p_actor_id returning id into link;
    if not found then raise exception using errcode='PT404',message='Telegram account is not linked'; end if;
    if not p_notifications_enabled then
        update telegram_outbox set state='cancelled',lease_token=null,lease_until=null
            where link_id=link and state in ('pending','sending');
    end if;
    return telegram_status(p_actor_id);
end;
$$;

create function public.queue_telegram_notification()
returns trigger language plpgsql security definer set search_path=public,pg_temp as $$
declare link uuid;
begin
    select id into link from telegram_links where employee_id=new.employee_id and notifications_enabled for share;
    if found then
        insert into telegram_outbox(link_id,notification_id) values(link,new.id)
            on conflict(notification_id) do nothing;
    end if;
    return new;
end;
$$;
create trigger queue_telegram_notification after insert on public.notifications
    for each row execute function public.queue_telegram_notification();

create function public.claim_telegram_outbox(p_limit integer default 20)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare result jsonb;
begin
    if p_limit is null or p_limit<1 or p_limit>100 then raise exception using errcode='PT422',message='Invalid delivery limit'; end if;
    update telegram_outbox set state='cancelled',lease_token=null,lease_until=null
        where attempts>=8 and state in ('pending','sending') and (lease_until is null or lease_until<now());
    with selected as (
        select o.id from telegram_outbox o join telegram_links l on l.id=o.link_id
        where l.notifications_enabled and o.attempts<8 and (
            (o.state='pending' and o.available_at<=now()) or (o.state='sending' and o.lease_until<now()))
        order by o.created_at,o.id for update of o skip locked limit p_limit
    ), claimed as (
        update telegram_outbox o set state='sending',attempts=attempts+1,
            lease_token=gen_random_uuid(),lease_until=now()+interval '2 minutes'
        from selected s where o.id=s.id returning o.*
    )
    select coalesce(jsonb_agg(jsonb_build_object('id',c.id,'link_id',c.link_id,'lease_token',c.lease_token,
        'chat_id',l.chat_id,'telegram_user_id',l.telegram_user_id,'title',n.title,'body',n.body,
        'notification_id',n.id,'request_id',n.request_id,'course_id',n.course_id,'ticket_id',n.ticket_id,
        'attempts',c.attempts) order by c.created_at,c.id),'[]'::jsonb) into result
        from claimed c join telegram_links l on l.id=c.link_id join notifications n on n.id=c.notification_id;
    return result;
end;
$$;

create function public.ack_telegram_outbox(p_delivery_id uuid,p_lease_token uuid,p_status text,p_retry_after_seconds integer default 30)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare delivery public.telegram_outbox; link uuid;
begin
    if p_status is null or p_status not in ('sent','retry','blocked') or p_retry_after_seconds is null
        or p_retry_after_seconds<1 or p_retry_after_seconds>86400 then
        raise exception using errcode='PT422',message='Invalid delivery acknowledgement';
    end if;
    -- Settings and acknowledgement lock link then delivery in the same order.
    select link_id into link from telegram_outbox where id=p_delivery_id;
    perform 1 from telegram_links where id=link for update;
    select * into delivery from telegram_outbox where id=p_delivery_id and state='sending'
        and lease_token=p_lease_token and lease_until>now() for update;
    if not found then return jsonb_build_object('recorded',false); end if;
    update telegram_outbox set state=case when p_status='retry' then case when attempts>=8 then 'cancelled' else 'pending' end else p_status end,
        delivered_at=case when p_status='sent' then now() else null end,
        available_at=now()+make_interval(secs=>greatest(p_retry_after_seconds,least(3600,30*(2^least(attempts-1,7))::integer))),
        lease_token=null,lease_until=null where id=delivery.id;
    if p_status='blocked' then
        update telegram_links set notifications_enabled=false where id=delivery.link_id;
        update telegram_outbox set state='cancelled',lease_token=null,lease_until=null
            where link_id=delivery.link_id and state in ('pending','sending');
    end if;
    return jsonb_build_object('recorded',true);
end;
$$;

create function public.telegram_worker_offset(p_bot_id bigint,p_offset bigint default null)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare current_offset bigint;
begin
    if p_bot_id is null or p_bot_id<=0 or p_offset<0 then raise exception using errcode='PT422',message='Invalid update offset'; end if;
    insert into telegram_worker_state(bot_id,update_offset) values(p_bot_id,coalesce(p_offset,0))
        on conflict(bot_id) do update set update_offset=greatest(telegram_worker_state.update_offset,excluded.update_offset)
        returning update_offset into current_offset;
    return jsonb_build_object('bot_id',p_bot_id,'offset',current_offset);
end;
$$;

revoke execute on function public.telegram_status(uuid),public.issue_telegram_link(uuid,text),
    public.consume_telegram_link(text,bigint,bigint,text),public.resolve_telegram_actor(bigint),
    public.unlink_telegram(uuid),public.set_telegram_settings(uuid,boolean),public.queue_telegram_notification(),
    public.claim_telegram_outbox(integer),public.ack_telegram_outbox(uuid,uuid,text,integer),
    public.telegram_worker_offset(bigint,bigint) from public,anon,authenticated;
grant execute on function public.telegram_status(uuid),public.issue_telegram_link(uuid,text),
    public.consume_telegram_link(text,bigint,bigint,text),public.resolve_telegram_actor(bigint),
    public.unlink_telegram(uuid),public.set_telegram_settings(uuid,boolean),
    public.claim_telegram_outbox(integer),public.ack_telegram_outbox(uuid,uuid,text,integer),
    public.telegram_worker_offset(bigint,bigint) to service_role;

notify pgrst,'reload schema';
commit;
