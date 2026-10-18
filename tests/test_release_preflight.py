import httpx
import pytest

from scripts import check_release


@pytest.mark.parametrize("broken", [None, "database", "authorization", "frontend"])
def test_preflight_rejects_partial_readiness(monkeypatch, broken):
    def respond(request):
        path = request.url.path
        if path in ("/", "/calendar"):
            return httpx.Response(
                200,
                text="API only"
                if broken == "frontend"
                else '<script src="/assets/app.js"></script>',
            )
        if path.endswith("/ready"):
            return httpx.Response(
                200, json={"status": "not_ready" if broken == "database" else "ready"}
            )
        if path.endswith("/live"):
            return httpx.Response(200, json={"status": "alive"})
        if path.startswith("/assets/"):
            return httpx.Response(404)
        return httpx.Response(200 if broken == "authorization" else 401)

    client = httpx.Client
    monkeypatch.setattr(
        check_release.httpx,
        "Client",
        lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(respond)),
    )
    assert check_release.check("http://portal.test")["passed"] is (broken is None)
