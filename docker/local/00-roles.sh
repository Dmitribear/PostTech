#!/bin/sh
set -eu
# Runs only when the dedicated PostgreSQL volume is empty.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v local_password="$POSTGRES_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE ROLE anon NOLOGIN;
CREATE ROLE authenticated NOLOGIN;
CREATE ROLE service_role NOLOGIN BYPASSRLS;
CREATE ROLE authenticator NOINHERIT LOGIN PASSWORD :'local_password';
GRANT anon, authenticated, service_role TO authenticator;
CREATE ROLE supabase_auth_admin NOINHERIT CREATEROLE LOGIN PASSWORD :'local_password';
CREATE SCHEMA auth AUTHORIZATION supabase_auth_admin;
ALTER ROLE supabase_auth_admin SET search_path = auth, public;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE supabase_auth_admin IN SCHEMA auth GRANT SELECT ON TABLES TO service_role;
GRANT ALL ON SCHEMA public TO postgres;
CREATE SCHEMA posttech_bootstrap AUTHORIZATION postgres;
REVOKE ALL ON SCHEMA posttech_bootstrap FROM PUBLIC;
CREATE TABLE posttech_bootstrap.identity (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), purpose text NOT NULL);
INSERT INTO posttech_bootstrap.identity(purpose) VALUES ('posttech-local-docker');
SQL
