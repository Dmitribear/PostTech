"""Shared manual ICS exports retain the request API's server-side scope."""

from datetime import date
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from icalendar import Calendar

from app.main import app
from app.application.use_cases import calendar_export, requests as workflow
from app.infrastructure.calendar_export import project_leave_calendar, leave_calendar
from test_requests import api, Query, request_row, as_user, WORKER, OTHER, MANAGER, HR

PATH = "/api/v1/requests/calendar.ics"
DIRECTOR = str(UUID(int=5))


def leave(index=10, employee=WORKER, approver=MANAGER, **changes):
    return {
        **request_row(employee, str(UUID(int=index))),
        "status": "approved",
        "approver_ids": [approver],
        "start_date": "2026-11-10",
        "end_date": "2026-11-12",
        **changes,
    }


def events(response):
    assert response.status_code == 200, response.text
    return Calendar.from_ical(response.content).walk("VEVENT")


def event_ids(response):
    return {
        str(event["uid"])[6:].removesuffix("@posttech.local")
        for event in events(response)
    }


@pytest.fixture(autouse=True)
def date_query_operators(monkeypatch):
    def gte(self, field, value):
        self.filters.append(
            lambda row: row.get(field) is not None and row[field] >= value
        )
        return self

    def lte(self, field, value):
        self.filters.append(
            lambda row: row.get(field) is not None and row[field] <= value
        )
        return self

    monkeypatch.setattr(Query, "gte", gte, raising=False)
    monkeypatch.setattr(Query, "lte", lte, raising=False)


def test_multi_event_dates_uid_and_private_fields_are_preserved():
    rows = [
        leave(10, start_date="2026-10-31", end_date="2026-11-02"),
        leave(11, start_date="2028-02-29", end_date="2028-02-29"),
        leave(12, start_date="2026-12-31", end_date="2026-12-31"),
    ]
    rows[0].update(
        comment="PRIVATE COMMENT\r\nATTENDEE:secret@example.test",
        full_name="Private Name",
        amount=9999,
        reviewer_comment="PRIVATE REVIEW",
    )
    raw = project_leave_calendar(rows)
    parsed = Calendar.from_ical(raw).walk("VEVENT")
    assert len(parsed) == 3
    assert [event.decoded("dtend") for event in parsed] == [
        date(2026, 11, 3),
        date(2028, 3, 1),
        date(2027, 1, 1),
    ]
    for row, event in zip(rows, parsed):
        assert (
            event["uid"]
            == Calendar.from_ical(leave_calendar(row)).walk("VEVENT")[0]["uid"]
        )
        assert event["class"] == "PRIVATE" and event["status"] == "CONFIRMED"
    assert all(
        value not in raw.decode()
        for value in [
            "PRIVATE COMMENT",
            "Private Name",
            "9999",
            "PRIVATE REVIEW",
            "ATTENDEE",
            "secret@example.test",
        ]
    )
    assert all(len(line) <= 75 for line in raw.split(b"\r\n"))
    assert raw.endswith(b"\r\n")


def test_project_export_requires_authentication():
    with TestClient(app) as client:
        assert client.get(PATH).status_code == 401


@pytest.mark.parametrize(
    "role,actor,visible",
    [
        ("worker", WORKER, {10}),
        ("manager", MANAGER, {10, 12}),
        ("director", DIRECTOR, {11, 13}),
        ("hr_admin", HR, {10, 11, 12, 13, 14}),
    ],
)
def test_all_scope_never_broadens_existing_request_access(api, role, actor, visible):
    client, database, identity = api
    database.tables["hr_requests"] = [
        leave(10),
        leave(11, OTHER, DIRECTOR),
        leave(12, MANAGER, HR),
        leave(13, DIRECTOR, HR),
        leave(14, HR, HR),
    ]
    as_user(identity, actor, role)
    response = client.get(PATH + "?scope=all")
    assert event_ids(response) == {str(UUID(int=value)) for value in visible}
    assert response.headers["x-calendar-event-count"] == str(len(visible))
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-type"].startswith("text/calendar")
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="janapost-leaves.ics"'
    )


@pytest.mark.parametrize(
    "role,actor", [("manager", MANAGER), ("director", DIRECTOR), ("hr_admin", HR)]
)
def test_team_scope_matches_calendar_ui_and_excludes_own_leave(api, role, actor):
    client, database, identity = api
    database.tables["hr_requests"] = [leave(10, WORKER, actor), leave(11, actor, HR)]
    as_user(identity, actor, role)
    assert event_ids(client.get(PATH + "?scope=team")) == {str(UUID(int=10))}
    assert event_ids(client.get(PATH + "?scope=mine")) == {str(UUID(int=11))}


def test_worker_cannot_export_team_or_spoof_employee(api):
    client, _, _ = api
    assert client.get(PATH + "?scope=team").status_code == 403
    assert client.get(PATH + f"?employee_id={OTHER}").status_code == 403


def test_employee_filter_cannot_escape_manager_visibility(api):
    client, database, identity = api
    database.tables["hr_requests"] = [leave(10), leave(11, OTHER, DIRECTOR)]
    as_user(identity, MANAGER, "manager")
    assert events(client.get(PATH + f"?employee_id={OTHER}")) == []
    as_user(identity, HR, "hr_admin")
    assert event_ids(client.get(PATH + f"?employee_id={OTHER}")) == {str(UUID(int=11))}


def test_only_final_approved_leaves_are_exported_across_every_page(api):
    client, database, _ = api
    database.tables["hr_requests"] = [leave(index) for index in range(100, 307)] + [
        leave(400, status="pending"),
        leave(401, status="pending_hr"),
        leave(402, status="pending_director"),
        leave(403, status="rejected"),
        leave(404, status="cancelled"),
        leave(405, request_type="advance"),
        leave(406, employee=OTHER, approver=DIRECTOR),
    ]
    response = client.get(PATH)
    assert event_ids(response) == {str(UUID(int=index)) for index in range(100, 307)}
    assert response.headers["x-calendar-event-count"] == "207"


def test_month_overlap_preserves_full_leave_dates_and_empty_selection(api):
    client, database, _ = api
    database.tables["hr_requests"] = [
        leave(10, start_date="2026-10-31", end_date="2026-11-02"),
        leave(11, start_date="2026-11-30", end_date="2026-12-02"),
        leave(12, start_date="2026-12-01", end_date="2026-12-02"),
        leave(13, start_date="2026-10-01", end_date="2026-10-31"),
    ]
    response = client.get(PATH + "?start_date=2026-11-01&end_date=2026-11-30")
    found = {str(event["uid"]): event for event in events(response)}
    assert len(found) == 2
    assert found[f"leave-{UUID(int=10)}@posttech.local"].decoded("dtstart") == date(
        2026, 10, 31
    )
    assert found[f"leave-{UUID(int=11)}@posttech.local"].decoded("dtend") == date(
        2026, 12, 3
    )
    response = client.get(PATH + "?start_date=2027-01-01&end_date=2027-01-31")
    assert events(response) == [] and response.headers["x-calendar-event-count"] == "0"


@pytest.mark.parametrize(
    "query",
    [
        "scope=foreign",
        "employee_id=invalid",
        "start_date=invalid",
        "start_date=2026-02-30",
        "start_date=2026-12-01&end_date=2026-11-30",
    ],
)
def test_invalid_filters_fail_before_database_access(api, monkeypatch, query):
    client, _, _ = api
    monkeypatch.setattr(
        workflow,
        "get_data_gateway",
        lambda: pytest.fail("Invalid filters must not read data"),
    )
    assert client.get(PATH + "?" + query).status_code == 422


def test_invalid_approved_leave_does_not_produce_partial_export(api):
    client, database, _ = api
    database.tables["hr_requests"] = [leave(10), leave(11, start_date=None)]
    response = client.get(PATH)
    assert response.status_code == 409
    assert "BEGIN:VCALENDAR" not in response.text


def test_export_size_guard_refuses_instead_of_truncating(api, monkeypatch):
    client, database, _ = api
    database.tables["hr_requests"] = [leave(10), leave(11), leave(12)]
    monkeypatch.setattr(calendar_export, "MAX_CALENDAR_EVENTS", 2)
    assert client.get(PATH).status_code == 413


def test_changing_pagination_is_not_silently_deduplicated(api, monkeypatch):
    client, _, _ = api
    page = [leave(index) for index in range(100, 200)]
    monkeypatch.setattr(
        workflow,
        "list_requests",
        lambda *args, **kwargs: page if kwargs["offset"] == 0 else [page[0]],
    )
    assert client.get(PATH).status_code == 503


def test_storage_failure_is_safe_and_not_an_empty_calendar(api, monkeypatch):
    client, _, _ = api

    def unavailable():
        raise RuntimeError("private database credentials")

    monkeypatch.setattr(workflow, "get_data_gateway", unavailable)
    response = client.get(PATH)
    assert response.status_code == 503 and "credentials" not in response.text
