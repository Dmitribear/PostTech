from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.application.use_cases import profile
from app.domain.errors import ApplicationError
from app.domain.models import UserContext


@pytest.mark.parametrize("role", ["manager", "director", "hr_admin"])
def test_team_cursor_is_bounded_and_role_scoped(monkeypatch, role):
    query = Mock()
    for method in ("select", "eq", "gt", "order", "limit"):
        getattr(query, method).return_value = query
    query.execute.return_value = SimpleNamespace(
        data=[{"id": str(i), "auth_user_id": "private"} for i in range(1, 4)]
    )
    gateway = Mock()
    gateway.table.return_value = query
    monkeypatch.setattr(profile, "get_data_gateway", lambda: gateway)
    result = profile.team_page(
        UserContext(id="actor", auth_user_id="auth", role=role, full_name="Actor"),
        after="0",
        limit=2,
    )
    assert result == {"items": [{"id": "1"}, {"id": "2"}], "next_cursor": "2"}
    query.limit.assert_called_once_with(3)
    query.gt.assert_called_once_with("id", "0")
    if role == "hr_admin":
        query.eq.assert_not_called()
    else:
        query.eq.assert_called_once_with("manager_id", "actor")


def test_worker_cannot_enumerate_employees():
    actor = UserContext(
        id="actor", auth_user_id="auth", role="worker", full_name="Actor"
    )
    with pytest.raises(ApplicationError) as failure:
        profile.team_page(actor)
    assert failure.value.status_code == 403
