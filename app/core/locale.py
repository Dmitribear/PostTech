"""Per-request content locale. Personal text is kept verbatim."""
from contextvars import ContextVar

locale: ContextVar[str] = ContextVar("locale",default="ru")


def course_content(course:dict) -> dict:
    result=dict(course)
    translations=result.pop("translations",{}) or {}
    translated=translations.get(locale.get())
    result["content_language"]="kk" if translated else "ru"
    if translated:
        for key in ("title","description","material_markdown","quiz"):
            if key in result and key in translated:
                result[key]=translated[key]
    return result


def notification_content(notification:dict) -> dict:
    if locale.get()!='kk':return notification
    titles={
      'request_created':'Жаңа өтінім','request_status_changed':'Өтінім мәртебесі өзгерді',
      'request_cancelled':'Өтінім кері қайтарылды','course_assigned':'Курс тағайындалды',
      'course_completed':'Курс аяқталды','team_course_completed':'Қызметкер курсты аяқтады',
      'course_deadline':'Оқу мерзімі өзгерді','delegation_assigned':'Сіз орынбасар болып тағайындалдыңыз',
      'hr_ticket_created':'HR-ға жаңа өтініш','hr_ticket_answered':'HR өтінішке жауап берді',
    }
    title=titles.get(notification.get('notification_type'))
    if not title:return notification
    # Preserve authored comments and exact historical messages for audit.
    return {**notification,'title':title,'body':'Толық ақпаратты карточкадан қараңыз.','original_body':notification.get('body','')}
