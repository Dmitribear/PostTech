"""Transactional invitations. Never log provider bodies, credentials or codes."""
from datetime import datetime
from html import escape

import httpx

from app.core.config import get_settings

ROLE_LABELS = {"worker": "Сотрудник", "manager": "Руководитель", "hr_admin": "HR-администратор"}


def configured() -> bool:
    key = get_settings().resend_api_key
    return bool(key and key.get_secret_value().strip())


def send(invitation: dict, code: str, token_hash: str) -> str:
    settings = get_settings()
    role = ROLE_LABELS[invitation["role"]]
    expires = datetime.fromisoformat(invitation["expires_at"].replace("Z", "+00:00"))
    expiry = expires.strftime("%d.%m.%Y %H:%M %z")
    text = (f"HR приглашает вас в PostTech.\n\nВаша роль: {role}\n"
            f"Подразделение: {invitation['department']}\nПочта: {invitation['email']}\n\n"
            f"Код приглашения: {code}\nДействует до: {expiry}\n\n"
            "На странице входа выберите «Активировать приглашение», вставьте код и задайте пароль. "
            "Затем подтвердите почту отдельным цифровым кодом из письма. Роль уже назначена HR.\n"
            "Если HR отправил приглашение повторно, используйте код из последнего письма.\n")
    if settings.portal_public_url:
        text += f"\nОткрыть PostTech: {settings.portal_public_url}\n"
    text += "\nЕсли вы не ожидали приглашения, обратитесь в HR. Никому не сообщайте пароль."
    # Escape every dynamic field, including names supplied by HR.
    html = ('<div style="font-family:Arial,sans-serif;max-width:560px;color:#152332">'
            '<h2>Приглашение в PostTech</h2>'
            f'<p style="white-space:pre-line;line-height:1.6">{escape(text)}</p></div>')
    try:
        response = httpx.post("https://api.resend.com/emails", timeout=15,
            headers={"Authorization": f"Bearer {settings.resend_api_key.get_secret_value()}",
                     "Idempotency-Key": f"invitation/{invitation['id']}/{token_hash}"},
            json={"from": settings.invitation_email_from,"to": [invitation["email"]],
                  "subject": f"PostTech — приглашение: {role}","text": text,"html": html})
        if 200 <= response.status_code < 300:
            return "accepted" if response.json().get("id") else "unknown"
        return "unknown" if response.status_code >= 500 else "failed"
    except (httpx.HTTPError, ValueError):
        # A timeout is not proof of non-delivery. Do not claim it failed or retry silently.
        return "unknown"
