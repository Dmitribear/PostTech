begin;

create or replace function public.cancel_hr_request(p_actor_id uuid, p_request_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = pg_catalog
as $$
declare
    v_request public.hr_requests%rowtype;
begin
    perform pg_advisory_xact_lock_shared(71007);
    select * into v_request from public.hr_requests where id = p_request_id for update;
    if not found then raise exception using errcode = 'PT404', message = 'Request not found'; end if;
    if p_actor_id is null or v_request.employee_id <> p_actor_id then
        raise exception using errcode = 'PT403', message = 'Only the owner can cancel a request';
    end if;
    if v_request.status = 'cancelled' then
        return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
    end if;
    if v_request.status <> 'pending' then
        raise exception using errcode = 'PT409', message = 'Only pending requests can be cancelled';
    end if;
    update public.hr_requests set status = 'cancelled', cancelled_at = now()
    where id = p_request_id returning * into v_request;
    insert into public.request_events (request_id, actor_id, event_type, from_status, to_status, comment, created_at)
    values (p_request_id, p_actor_id, 'cancelled', 'pending', 'cancelled', 'Отозвана автором', v_request.cancelled_at);
    insert into public.notifications (employee_id, request_id, notification_type, title, body)
    select e.id, p_request_id, 'request_cancelled', 'Заявка отозвана',
        case when e.id = p_actor_id then 'Вы отозвали заявку. Она больше не ожидает согласования.'
             else 'Автор отозвал заявку. Согласование больше не требуется.' end
    from public.employee_profiles e
    where e.id in (
        select p_actor_id
        union
        select unnest(v_request.approver_ids)
        union
        select d.deputy_id from public.approval_delegations d
        where d.manager_id = any(v_request.approver_ids)
          and exists (
              select 1 from public.active_delegation_principals(d.deputy_id) principal
              where principal = any(v_request.approver_ids)
          )
    );
    return to_jsonb(v_request) - 'idempotency_key' - 'approver_ids';
end;
$$;

revoke execute on function public.cancel_hr_request(uuid, uuid) from public, anon, authenticated;
grant execute on function public.cancel_hr_request(uuid, uuid) to service_role;
notify pgrst, 'reload schema';

commit;
