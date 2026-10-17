from app.application.use_cases import requests as workflow
from app.domain.errors import ApplicationError

MAX_CALENDAR_EVENTS = 5000


def permitted_calendar_requests(
    actor, *, scope="all", employee_id=None, start_date=None, end_date=None
):
    """Read every permitted approved leave page; never silently truncate."""

    if scope not in {"mine", "team", "all"}:
        raise ApplicationError(422, "Unknown calendar scope")
    if scope == "team" and actor.role == "worker":
        raise ApplicationError(403, "Team calendar requires a reviewer role")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ApplicationError(422, "Calendar end date must not precede its start date")
    records, seen, offset = [], set(), 0
    while True:
        page = workflow.list_requests(
            actor,
            scope="review" if scope == "team" else scope,
            employee_id=employee_id,
            request_status="approved",
            request_type="leave",
            start_date=start_date,
            end_date=end_date,
            limit=100,
            offset=offset,
        )
        for request in page:
            if request["id"] in seen:
                raise ApplicationError(
                    503, "Calendar changed while loading; retry the export"
                )
            seen.add(request["id"])
            records.append(request)
        if len(records) > MAX_CALENDAR_EVENTS:
            raise ApplicationError(
                413, "Too many leave events; choose a narrower date range or employee"
            )
        if len(page) < 100:
            return records
        offset += len(page)
