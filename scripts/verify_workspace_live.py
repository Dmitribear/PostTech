"""Stages 7–10 rehearsal on explicitly marked fictional accounts only."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid4
from urllib.request import Request
import json
from verify_live_workflow import (
    API,
    ROOT,
    require,
    read_json,
    save_checkpoint,
    checkpoint_lock,
    now,
)


def run():
    api = API("http://127.0.0.1:8010")
    jury = read_json(ROOT / ".local/jury-credentials.json")
    scenario = read_json(ROOT / ".local/scenario-credentials.json")
    require(
        jury["project_ref"] == scenario["project_ref"] == "zcsoipcwymhowmvnytxf",
        "Wrong project",
    )
    accounts = {
        **{k: jury[k] for k in ("employee", "manager", "hr")},
        "deputy": scenario["director"],
    }
    profiles = {}
    for name, a in accounts.items():
        require(
            a["email"].endswith("@posttech.demo"), "Only synthetic accounts allowed"
        )
        auth = api.call(
            "POST", "/auth/login", body={k: a[k] for k in ("email", "password")}
        )
        api.tokens[name] = auth["access_token"]
        p = api.call("GET", "/profile", name)
        require(
            p["id"] == a["profile_id"]
            and p["external_source"]
            in ("posttech-jury-fixture", "posttech-scenario-check"),
            "Fixture marker missing",
        )
        profiles[name] = p
    path = ROOT / ".local/workspace-rehearsal.json"
    with checkpoint_lock(path):
        s = (
            read_json(path)
            if path.exists()
            else {
                "fixture_id": jury["fixture_id"],
                **{
                    k: str(uuid4())
                    for k in (
                        "delegation",
                        "request_key",
                        "blocked_key",
                        "course",
                        "course_v2",
                        "ticket",
                        "submission",
                    )
                },
                "date": datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat(),
            }
        )
        require(s["fixture_id"] == jury["fixture_id"], "Checkpoint mismatch")
        save_checkpoint(path, s)
        body = dict(
            id=s["delegation"],
            manager_id=profiles["manager"]["id"],
            deputy_id=profiles["deputy"]["id"],
            starts_on=s["date"],
            ends_on=s["date"],
            reason="Проверка стенда: временное согласование",
        )
        api.call("POST", "/workspace/delegations", "employee", body, expected=403)
        d = api.call("POST", "/workspace/delegations", "hr", body, expected=201)
        request = api.call(
            "POST",
            "/requests",
            "employee",
            dict(
                request_type="advance",
                amount=1700,
                comment="Проверка замещения · вымышленные данные",
            ),
            expected=201,
            key=s["request_key"],
        )
        blocked = api.call(
            "POST",
            "/requests",
            "employee",
            dict(
                request_type="advance",
                amount=1800,
                comment="Проверка отзыва замещения · вымышленные данные",
            ),
            expected=201,
            key=s["blocked_key"],
        )
        s["request_id"] = request["id"]
        s["blocked_request_id"] = blocked["id"]
        save_checkpoint(path, s)
        api.call(
            "GET", f"/employees/{profiles['employee']['id']}", "deputy", expected=403
        )
        if not d["revoked_at"]:
            detail = api.call("GET", f"/requests/{request['id']}", "deputy")
            require(
                detail["can_review"] or detail["status"] == "approved",
                "Delegate cannot review",
            )
            visible = api.call("GET", "/requests?scope=review", "deputy")
            require(
                any(r["id"] == request["id"] for r in visible),
                "Request missing in delegate queue",
            )
            api.call(
                "PATCH",
                f"/requests/{request['id']}/review",
                "deputy",
                dict(
                    status="approved",
                    reviewer_comment="Согласовано временным заместителем · проверка",
                ),
            )
            api.call("DELETE", f"/workspace/delegations/{d['id']}", "hr")
        api.call(
            "PATCH",
            f"/requests/{blocked['id']}/review",
            "deputy",
            dict(status="approved"),
            expected=403,
        )
        api.call("GET", f"/requests/{blocked['id']}", "deputy", expected=403)
        events = api.call("GET", f"/requests/{request['id']}/history", "employee")
        require(
            any(e.get("delegation_id") == s["delegation"] for e in events),
            "Delegation audit missing",
        )
        api.call("POST", f"/requests/{blocked['id']}/cancel", "employee")
        api.call("GET", "/workspace/courses", "employee", expected=403)
        quiz = [
            dict(
                id="request",
                prompt="Где создать заявку на отпуск?",
                options=["В разделе «Заявки»", "В профиле коллеги"],
                answer_index=0,
            )
        ]
        kk = dict(
            title="PostTech: өтінімдермен жұмыс",
            description="Порталдың оқу сценарийі.",
            material_markdown="# Өтінім жасау\n\n«Өтінімдер» бөлімін ашып, демалыс түрін таңдаңыз. Күндерді көрсетіп, жіберіңіз. Мәртебе карточкада көрсетіледі. Өз өтініміңізді келісуге болмайды.",
            quiz=[
                dict(
                    id="request",
                    prompt="Демалыс өтінімін қайдан жасауға болады?",
                    options=["«Өтінімдер» бөлімінен", "Әріптестің профилінен"],
                    answer_index=0,
                )
            ],
        )
        data = dict(
            title="PostTech: работа с заявками",
            description="Учебный сценарий работы с порталом.",
            material_markdown="# Создание заявки\n\nОткройте раздел «Заявки» и выберите отпуск. Укажите даты и отправьте заявку. Статус появится в карточке. Свою заявку согласовать нельзя.",
            quiz=quiz,
            translations={"kk": kk},
            duration_minutes=5,
            passing_score=80,
            category="PostTech",
            audience="Все сотрудники",
        )
        courses = api.call("GET", "/workspace/courses", "hr")
        course = next((c for c in courses if c["id"] == s["course"]), None)
        if not course:
            course = api.call(
                "POST",
                "/workspace/courses",
                "hr",
                dict(id=s["course"], action="create", data=data),
            )
        if course["publication_state"] == "draft":
            course = api.call(
                "POST",
                "/workspace/courses",
                "hr",
                dict(id=course["id"], action="publish", revision=course["revision"]),
            )
        mine = api.call("GET", "/academy/my-courses", "employee")
        assignment = next((a for a in mine if a["course_id"] == course["id"]), None)
        if not assignment:
            assignment = api.call(
                "POST",
                "/academy/assignments",
                "hr",
                dict(
                    employee_id=profiles["employee"]["id"],
                    course_id=course["id"],
                    due_on=s["date"],
                ),
                expected=201,
            )
        # A real localized HTTP response; tokens never printed or persisted.
        req = Request(
            api.base + f"/academy/courses/{course['id']}",
            headers={
                "Authorization": "Bearer " + api.tokens["employee"],
                "Accept-Language": "kk",
            },
        )
        with api.opener.open(req, timeout=30) as response:
            localized = json.load(response)
        require(
            localized["title"] == kk["title"] and "answer_index" not in str(localized),
            "Translation/quiz privacy failed",
        )
        courses = api.call("GET", "/workspace/courses", "hr")
        v2 = next((c for c in courses if c["id"] == s["course_v2"]), None)
        if not v2:
            v2 = api.call(
                "POST",
                "/workspace/courses",
                "hr",
                dict(
                    id=s["course_v2"],
                    action="create",
                    data={**data, "family_id": course["id"]},
                ),
            )
        if v2["publication_state"] == "draft":
            v2 = api.call(
                "POST",
                "/workspace/courses",
                "hr",
                dict(id=v2["id"], action="publish", revision=v2["revision"]),
            )
        api.call("GET", f"/academy/courses/{course['id']}", "employee")
        api.call(
            "PATCH",
            f"/academy/courses/{course['id']}/progress",
            "employee",
            dict(progress_percent=90),
        )
        result = api.call(
            "POST",
            f"/academy/courses/{course['id']}/complete",
            "employee",
            dict(answers={"request": 0}),
            key=s["submission"],
        )
        require(result["status"] == "completed", "Archived version cannot complete")
        api.call(
            "PATCH",
            f"/workspace/assignments/{assignment['id']}/deadline",
            "hr",
            dict(due_on=None),
            expected=409,
        )
        managers = api.call("GET", "/academy/my-courses", "manager")
        if not any(a["course_id"] == v2["id"] for a in managers):
            api.call(
                "POST",
                "/academy/assignments",
                "hr",
                dict(
                    employee_id=profiles["manager"]["id"],
                    course_id=v2["id"],
                    due_on=s["date"],
                ),
                expected=201,
            )
        ticket = dict(
            id=s["ticket"],
            question="Проверка: где уточнить условия переноса отпуска?",
            context="Демонстрационное обращение со стенда. Личные данные не передаются.",
            consent=True,
        )
        first = api.call("POST", "/workspace/tickets", "employee", ticket, expected=201)
        require(
            api.call("POST", "/workspace/tickets", "employee", ticket, expected=201)[
                "id"
            ]
            == first["id"],
            "Duplicate ticket",
        )
        api.call("GET", f"/workspace/tickets/{first['id']}", "manager", expected=404)
        api.call(
            "POST",
            f"/workspace/tickets/{first['id']}/answer",
            "manager",
            dict(answer="Недопустимый ответ"),
            expected=403,
        )
        api.call(
            "POST",
            f"/workspace/tickets/{first['id']}/answer",
            "hr",
            dict(
                answer="Это учебный ответ: условия переноса нужно согласовать с вашим HR. Обращение получено, ответ сохранён в портале."
            ),
        )
        require(
            api.call("GET", f"/workspace/tickets/{first['id']}", "employee")["status"]
            == "resolved",
            "HR reply missing",
        )
        notes = api.rows("/notifications", "employee")
        require(
            any(n.get("ticket_id") == s["ticket"] for n in notes),
            "Ticket notification missing",
        )
        s.update(
            status="passed",
            checked_at=now(),
            checks=[
                "delegate_queue",
                "delegate_profile_forbidden",
                "delegate_approval_audit",
                "revocation_immediate",
                "course_editor_hr_only",
                "immutable_versions",
                "kk_material_and_quiz",
                "answer_keys_private",
                "archived_course_completion",
                "completed_deadline_immutable",
                "ticket_consent",
                "ticket_idempotency",
                "ticket_privacy",
                "hr_reply_notification",
            ],
        )
        save_checkpoint(path, s)
        return {k: s[k] for k in ("status", "checked_at", "checks")}


if __name__ == "__main__":
    try:
        print(json.dumps(run(), ensure_ascii=False))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "type": type(exc).__name__,
                    "message": str(exc)
                    if type(exc).__name__ == "VerificationError"
                    else "Inspect checkpoint; no credentials logged",
                }
            )
        )
        raise SystemExit(1)
