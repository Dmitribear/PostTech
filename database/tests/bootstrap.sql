-- Test-only Supabase prerequisites for a disposable local PostgreSQL instance.
create schema if not exists auth;
create table auth.users (id uuid primary key, email text not null);
do $$ begin
    if not exists (select 1 from pg_roles where rolname = 'service_role') then
        create role service_role nologin bypassrls;
        create role anon nologin;
        create role authenticated nologin;
    end if;
end $$;
insert into auth.users values
    ('30000000-0000-4000-8000-000000000001', 'hr@posttech.demo'),
    ('30000000-0000-4000-8000-000000000002', 'manager@posttech.demo'),
    ('30000000-0000-4000-8000-000000000003', 'employee@posttech.demo');
