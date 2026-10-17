from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import httpx

from app.db import supabase


def test_cached_clients_use_separate_http1_pools_for_auth_and_parallel_queries(monkeypatch):
    settings = SimpleNamespace(
        supabase_url="https://project.supabase.co",
        supabase_key="sb_secret_test_server",
        supabase_anon_key="sb_publishable_test_public",
    )
    monkeypatch.setattr(supabase, "get_settings", lambda: settings)
    clients = []
    options_seen = []
    requests = []
    parallel_queries = Barrier(2)

    def respond(request):
        requests.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={
                "id": "a83f486c-a376-4b8e-a9ef-bb2114247bc1",
                "aud": "authenticated",
                "role": "authenticated",
                "email": "worker@example.test",
                "app_metadata": {},
                "user_metadata": {},
                "created_at": "2026-10-16T10:00:00Z",
            })
        assert request.url.path == "/rest/v1/employee_profiles"
        parallel_queries.wait(timeout=5)
        return httpx.Response(200, json=[{"id": "employee-1"}])

    def make_http_client(**options):
        options_seen.append(options)
        client = httpx.Client(transport=httpx.MockTransport(respond), **options)
        clients.append(client)
        return client

    monkeypatch.setattr(supabase, "HttpxClient", make_http_client)
    supabase.get_supabase_client.cache_clear()
    supabase.get_supabase_auth_client.cache_clear()
    try:
        server = supabase.get_supabase_client()
        public = supabase.get_supabase_auth_client()
        assert supabase.get_supabase_client() is server
        assert supabase.get_supabase_auth_client() is public
        assert len(clients) == 2
        assert server.options.httpx_client is clients[0]
        assert public.options.httpx_client is clients[1]
        first_auth = supabase.create_supabase_auth_client()
        second_auth = supabase.create_supabase_auth_client()
        assert first_auth is not second_auth
        assert first_auth.auth is not second_auth.auth
        assert first_auth.options.httpx_client is public.options.httpx_client
        assert second_auth.options.httpx_client is public.options.httpx_client
        assert len(clients) == 2
        assert first_auth.options.persist_session is False
        assert first_auth.options.auto_refresh_token is False
        assert first_auth.options.flow_type == "implicit"
        for options in options_seen:
            assert options["http2"] is False
            assert options["timeout"].connect == 10
            assert options["timeout"].read == 30

        # Actual SDK Auth and REST calls must use our transport, not fall back
        # to their own default HTTP/2 clients. The barrier also rules out
        # serializing all dashboard requests as a workaround.
        assert server.auth.get_user("server-user-token").user.email == "worker@example.test"
        assert public.auth.get_user("public-user-token").user.email == "worker@example.test"

        def query_profile():
            return server.table("employee_profiles").select("id").execute().data

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: query_profile(), range(2)))
        assert results == [[{"id": "employee-1"}]] * 2
        assert [request.headers["apikey"] for request in requests] == [
            settings.supabase_key,
            settings.supabase_anon_key,
            settings.supabase_key,
            settings.supabase_key,
        ]
        assert all(
            request.headers["authorization"] == f"Bearer {settings.supabase_key}"
            for request in requests if request.url.path.startswith("/rest/")
        )
    finally:
        for client in clients:
            client.close()
        supabase.get_supabase_client.cache_clear()
        supabase.get_supabase_auth_client.cache_clear()
