"""Read-only iCalendar export using authoritative approved leave dates."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from icalendar import Calendar, Event


class CalendarExportUnavailable(ValueError):
    """This request cannot be represented as an approved leave event."""


def leave_calendar(request: dict, *, demo: bool = False) -> bytes:
    if request.get("request_type") != "leave" or request.get("status") != "approved":
        raise CalendarExportUnavailable(
            "Calendar export requires an approved leave request"
        )
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
    event.add(
        "description",
        "Одобренный отпуск. Импорт файла не синхронизирует изменения: при переносе или отмене обновите событие вручную.",
    )
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
        event["summary"] = (
            str(event["summary"]) + " · " + str(UUID(str(request["id"])))[:8]
        )
        calendar.add_component(event)
    return calendar.to_ical()
