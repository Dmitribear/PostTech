begin;

-- Seek pagination and team filtering; no offset scan across employee history.
create index if not exists employee_profiles_manager_cursor_idx
    on public.employee_profiles(manager_id,id);
create index if not exists hr_requests_employee_created_cursor_idx
    on public.hr_requests(employee_id,created_at desc,id desc);
create index if not exists hr_requests_pending_created_idx
    on public.hr_requests(created_at,id) where status='pending';
create index if not exists request_events_request_cursor_idx
    on public.request_events(request_id,created_at,id);
create index if not exists notifications_employee_unread_cursor_idx
    on public.notifications(employee_id,created_at desc,id desc) where read_at is null;
create index if not exists course_assignments_due_open_idx
    on public.course_assignments(due_on,employee_id) where status<>'completed' and due_on is not null;
create index if not exists registration_invitations_active_expiry_idx
    on public.registration_invitations(expires_at,id) where consumed_at is null and revoked_at is null;
create index if not exists fulfillment_queue_cursor_idx
    on public.request_fulfillment(status,updated_at,request_id);

commit;
