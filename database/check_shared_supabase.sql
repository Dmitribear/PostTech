-- Read-only inspection before connecting Integration to an existing Supabase.
-- Run in the confirmed shared project's SQL Editor. No employee data or keys
-- are returned. This script does not create, alter, seed or delete anything.
with expected_tables(name) as (
    values ('employee_profiles'), ('hr_requests'), ('request_events'),
           ('hr_request_events'), ('notifications'), ('knowledge_articles'),
           ('courses'), ('course_assignments')
), table_status as (
    select expected.name,
           relation.oid is not null as present,
           relation.relrowsecurity as rls_enabled,
           coalesce((
               select jsonb_agg(attribute.attname order by attribute.attnum)
               from pg_catalog.pg_attribute attribute
               where attribute.attrelid = relation.oid
                 and attribute.attnum > 0 and not attribute.attisdropped
           ), '[]'::jsonb) as columns
    from expected_tables expected
    left join pg_catalog.pg_class relation
      on relation.oid = to_regclass(format('public.%I', expected.name))
), workflow_functions as (
    select routine.proname as name,
           pg_get_function_identity_arguments(routine.oid) as arguments,
           routine.prosecdef as security_definer,
           has_function_privilege('anon', routine.oid, 'EXECUTE') as anon_can_execute,
           has_function_privilege('authenticated', routine.oid, 'EXECUTE') as user_can_execute,
           has_function_privilege('service_role', routine.oid, 'EXECUTE') as server_can_execute
    from pg_catalog.pg_proc routine
    join pg_catalog.pg_namespace namespace on namespace.oid = routine.pronamespace
    where namespace.nspname = 'public'
      and routine.proname in ('create_hr_request', 'review_hr_request')
), workflow_triggers as (
    select relation.relname as table_name, trigger.tgname as name,
           trigger.tgenabled as enabled, routine.proname as function_name
    from pg_catalog.pg_trigger trigger
    join pg_catalog.pg_class relation on relation.oid = trigger.tgrelid
    join pg_catalog.pg_namespace namespace on namespace.oid = relation.relnamespace
    join pg_catalog.pg_proc routine on routine.oid = trigger.tgfoid
    where not trigger.tgisinternal and namespace.nspname = 'public'
      and relation.relname in ('hr_requests', 'course_assignments')
)
select jsonb_build_object(
    'tables', (select jsonb_agg(to_jsonb(table_status) order by name) from table_status),
    'workflow_functions', coalesce((select jsonb_agg(to_jsonb(workflow_functions) order by name) from workflow_functions), '[]'::jsonb),
    'workflow_triggers', coalesce((select jsonb_agg(to_jsonb(workflow_triggers) order by table_name, name) from workflow_triggers), '[]'::jsonb),
    'ver2_request_trigger_present', exists (
        select 1 from workflow_triggers where name = 'hr_requests_record_events'
    )
) as schema_report;
