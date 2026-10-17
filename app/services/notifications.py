from supabase import Client

from app.db.supabase import get_supabase_client


def list_employee_notifications(client: Client, employee_id: str) -> list[dict]:
    """Load the latest 100 notifications for the authorized employee."""
    response = (
        client.table("notifications")
        .select("*")
        .eq("employee_id", employee_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return response.data or []


def create_notification(
    employee_id: str,
    title: str,
    body: str,
    notification_type: str,
    request_id: str | None = None,
) -> None:
    get_supabase_client().table("notifications").insert(
        {
            "employee_id": employee_id,
            "request_id": request_id,
            "notification_type": notification_type,
            "title": title,
            "body": body,
        }
    ).execute()


def notify_hr(title: str, body: str, notification_type: str, request_id: str) -> None:
    response = (
        get_supabase_client()
        .table("employee_profiles")
        .select("id")
        .eq("role", "hr_admin")
        .execute()
    )
    for profile in response.data or []:
        create_notification(
            str(profile["id"]), title, body, notification_type, request_id
        )
