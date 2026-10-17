"""Read-only iCalendar export using authoritative approved leave dates."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from icalendar import Calendar, Event

MAX_CALENDAR_EVENTS = 10000


class CalendarExportUnavailable(ValueError):
    """This request cannot be represented as an approved leave event."""


def leave_calendar(request: dict, *, demo: bool = False) -> bytes:
    if request.get("request_type") != "leave" or request.get("status") != "approved":
        raise CalendarExportUnavailable("Calendar export requires an approved leave request")
    try:
        request_id = UUID(str(request["id"]))
        start = date.fromisoformat(str(request["start_date"]))
        end = date.fromisoformat(str(request["end_date"]))
        if end < start:
            raise ValueError("Invalid date range")
        # RFC 5545: DTEND is exclusive, HR end_date is inclusive.
        exclusive_end = end + timedelta(days=1)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CalendarExportUnavailable("Leave dates are missing or invalid") from exc

    event = Event()
    event.add("uid", f"leave-{request_id}@posttech.local")
    event.add("dtstamp", datetime.now(UTC))
    event.add("dtstart", start)
    event.add("dtend", exclusive_end)
    event.add("summary", ("Демо: " if demo else "") + "Отпуск — JanaPost")
    event.add("description", "Одобренный отпуск. Импорт файла не синхронизирует изменения: при переносе или отмене обновите событие вручную.")
    event.add("status", "CONFIRMED")
    event.add("class", "PRIVATE")
    event.add("transp", "OPAQUE")
    calendar = Calendar()
    calendar.add("prodid", "-//PostTech//Jana Leave Export//RU")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add_component(event)
    # The library handles UTF-8, escaping, CRLF and octet-aware line folding.
    return calendar.to_ical()


def project_leave_calendar(requests: list[dict]) -> bytes:
    """Combine authorized leave events without copying private HR fields.

    Reuse the individual export's UID and date semantics. This is a manual
    import file, not a subscription or access grant to a Google calendar.
    """
    calendar = Calendar()
    calendar.add("prodid", "-//PostTech//Jana Leave Export//RU")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("x-wr-calname", "Отпуска — JanaPost")
    for request in requests:
        event = Calendar.from_ical(leave_calendar(request)).walk("VEVENT")[0]
        # Distinguish overlapping leaves without reading additional profiles.
        event["summary"] = str(event["summary"]) + " · " + str(UUID(str(request["id"])))[:8]
        calendar.add_component(event)
    return calendar.to_ical()


def permitted_calendar_requests(actor, *, scope="all", employee_id=None, start_date=None, end_date=None):
    """Read every permitted approved leave page; never silently truncate."""
    from fastapi import HTTPException
    from app.services.requests import list_requests

    if scope not in {"mine", "team", "all"}:
        raise HTTPException(422, "Unknown calendar scope")
    if scope == "team" and actor.role == "worker":
        raise HTTPException(403, "Team calendar requires a reviewer role")
    if start_date is not None and end_date is not None and end_date < start_date:
        raise HTTPException(422, "Calendar end date must not precede its start date")
    records, seen, offset = [], set(), 0
    while True:
        page = list_requests(actor, scope="review" if scope == "team" else scope,
                             employee_id=employee_id, request_status="approved", request_type="leave",
                             start_date=start_date, end_date=end_date, limit=100, offset=offset)
        for request in page:
            if request["id"] in seen:
                raise HTTPException(503, "Calendar changed while loading; retry the export")
            seen.add(request["id"])
            records.append(request)
        if len(records) > MAX_CALENDAR_EVENTS:
            raise HTTPException(413, "Too many leave events; choose a narrower date range or employee")
        if len(page) < 100:
            return records
        offset += len(page)
