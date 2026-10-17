"""Real API rehearsal, exclusively on the existing marked fictional jury accounts.

Creates one course with two lessons and one draft/archived test knowledge source.
Creates at most one one-day leave (if capacity exists), otherwise one advance.
Never starts integration delivery. Credentials/tokens remain private.
"""

from datetime import date, timedelta
from uuid import uuid4
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
    api = API("http://127.0.0.1:8000")
    credentials = read_json(ROOT / ".local/jury-credentials.json")
    require(credentials["project_ref"] == "zcsoipcwymhowmvnytxf", "Unexpected project")
    profiles = {}
    for role in ("employee", "manager", "hr"):
        account = credentials[role]
        require(
            account["email"]
            == f"jury.{role}+{credentials['fixture_id']}@posttech.demo",
            "Not a jury account",
        )
        auth = api.call(
            "POST", "/auth/login", body={k: account[k] for k in ("email", "password")}
        )
        api.tokens[role] = auth["access_token"]
        profile = api.call("GET", "/profile", role)
        require(
            profile["external_source"] == "posttech-jury-fixture"
            and profile["id"] == account["profile_id"],
            "Synthetic marker missing",
        )
        profiles[role] = profile
    checkpoint = ROOT / ".local/extensions-live.json"
    with checkpoint_lock(checkpoint):
        state = (
            read_json(checkpoint)
            if checkpoint.exists()
            else dict(
                fixture_id=credentials["fixture_id"],
                **{
                    name: str(uuid4())
                    for name in ("course", "knowledge", "request_key", "quiz_key")
                },
            )
        )
        require(state["fixture_id"] == credentials["fixture_id"], "Checkpoint mismatch")
        save_checkpoint(checkpoint, state)
        balance = api.call("GET", "/workspace/leave-balance", "employee")
        require(
            balance["available_days"]
            == balance["official_days"]
            - balance["pending_days"]
            - balance["approved_unreconciled_days"],
            "Balance formula mismatch",
        )
        api.call("GET", "/workspace/knowledge", "employee", expected=403)
        api.call("GET", "/workspace/integrations", "manager", expected=403)
        if "request_body" not in state:
            requests = api.call(
                "GET", "/requests?scope=mine&request_type=leave&limit=100", "employee"
            )
            # A small, explicit demo request. Do not edit existing requests or balances.
            day = date.today() + timedelta(days=120)
            while any(
                r["status"] in ("pending", "approved")
                and r["start_date"] <= day.isoformat() <= r["end_date"]
                for r in requests
            ):
                day += timedelta(days=1)
            state["request_body"] = (
                dict(
                    request_type="leave",
                    start_date=day.isoformat(),
                    end_date=day.isoformat(),
                    comment="Проверка резерва и очереди · вымышленный сотрудник",
                )
                if balance["available_days"] >= 1
                else dict(
                    request_type="advance",
                    amount=1100,
                    comment="Проверка очереди · вымышленный сотрудник",
                )
            )
            save_checkpoint(checkpoint, state)
        request = api.call(
            "POST",
            "/requests",
            "employee",
            state["request_body"],
            expected=201,
            key=state["request_key"],
        )
        request = api.call(
            "PATCH",
            f"/requests/{request['id']}/review",
            "manager",
            dict(status="approved", reviewer_comment="Проверка интеграционной очереди"),
        )
        api.call(
            "PATCH",
            f"/requests/{request['id']}/review",
            "manager",
            dict(status="approved", reviewer_comment="Проверка интеграционной очереди"),
        )
        events = []
        offset = 0
        while True:
            queue = api.call("GET", f"/workspace/integrations?offset={offset}", "hr")
            require(
                not any(queue["connected"].values()),
                "External delivery must remain disabled for this rehearsal",
            )
            events.extend(
                e for e in queue["events"] if e["aggregate_id"] == request["id"]
            )
            if len(queue["events"]) < 20:
                break
            offset += 20
        require(
            len(events) == 2
            and all(e["status"] == "queued" and e["attempts"] == 0 for e in events),
            "Approval outbox duplication or unexpected delivery",
        )
        state["request_id"] = request["id"]
        content = dict(
            title="PostTech: отпуск и согласование",
            description="Два коротких урока о работе с заявками.",
            duration_minutes=5,
            passing_score=80,
            category="PostTech",
            audience="Все сотрудники",
            material_markdown="Изучите два урока и ответьте на один вопрос.",
            translations={},
            lessons=[
                dict(
                    id="request",
                    title="Оформление отпуска",
                    material_markdown="Выберите даты в календаре. Проверьте доступные дни и согласующего. Отправьте заявку. Дни будут зарезервированы до решения.",
                ),
                dict(
                    id="decision",
                    title="Решение и остаток",
                    material_markdown="Руководитель согласует или отклоняет заявку. При отказе резерв освобождается. Согласованный отпуск остаётся в резерве до сверки кадрового остатка.",
                ),
            ],
            quiz=[
                dict(
                    id="q1",
                    prompt="Что происходит с резервом при отказе?",
                    options=["Освобождается", "Списывается повторно"],
                    answer_index=0,
                )
            ],
        )
        course = next(
            (
                c
                for c in api.call("GET", "/workspace/courses", "hr")
                if c["id"] == state["course"]
            ),
            None,
        )
        if not course:
            course = api.call(
                "POST",
                "/workspace/courses",
                "hr",
                dict(id=state["course"], action="create", data=content),
            )
        if course["publication_state"] == "draft":
            course = api.call(
                "POST",
                "/workspace/courses",
                "hr",
                dict(id=course["id"], action="publish", revision=course["revision"]),
            )
        mine = api.call("GET", "/academy/my-courses", "employee")
        assigned = next((a for a in mine if a["course_id"] == course["id"]), None)
        if not assigned:
            assigned = api.call(
                "POST",
                "/academy/assignments",
                "hr",
                dict(employee_id=profiles["employee"]["id"], course_id=course["id"]),
                expected=201,
            )
        if assigned["progress_percent"] < 90:
            api.call(
                "PATCH",
                f"/academy/courses/{course['id']}/progress",
                "employee",
                dict(progress_percent=90),
                expected=409,
            )
        for lesson in ("request", "decision"):
            api.call(
                "POST",
                f"/workspace/courses/{course['id']}/lessons/{lesson}/complete",
                "employee",
            )
        result = api.call(
            "POST",
            f"/academy/courses/{course['id']}/complete",
            "employee",
            dict(answers={"q1": 0}),
            key=state["quiz_key"],
        )
        require(
            result["status"] == "completed"
            and len(result["completed_lesson_ids"]) == 2,
            "Lesson completion failed",
        )
        article = api.call(
            "POST",
            "/workspace/knowledge",
            "hr",
            dict(
                id=state["knowledge"],
                action="create",
                data=dict(
                    title="Тест редактора источников",
                    content="Служебный тест редактора. Это не кадровая политика и не инструкция сотрудникам.",
                    source_title="Тестовая запись PostTech",
                    keywords=["editor-fixture"],
                ),
            ),
        )
        if article["editorial_state"] == "draft":
            article = api.call(
                "POST",
                "/workspace/knowledge",
                "hr",
                dict(
                    id=article["id"],
                    revision=article["revision"],
                    action="approve",
                    due=(date.today() + timedelta(days=30)).isoformat(),
                ),
            )
        if article["active"]:
            api.call(
                "POST",
                "/workspace/knowledge",
                "hr",
                dict(id=article["id"], revision=article["revision"], action="archive"),
            )
        api.call("GET", f"/ai/sources/{article['id']}", "employee", expected=404)
        state.update(
            verified_at=now(),
            calls=api.calls,
            outbox_events=2,
            lesson_status="completed",
            knowledge_status="archived",
            request_type=request["request_type"],
        )
        save_checkpoint(checkpoint, state)
        public = dict(
            verified_at=state["verified_at"],
            scope="Docker API + real Supabase, synthetic jury accounts only",
            api_calls=api.calls,
            request_type=request["request_type"],
            outbox_events=2,
            external_delivery_enabled=False,
            course_lessons=2,
            course_result=result["status"],
            knowledge_result="created, approved, archived; employee access denied after archive",
        )
        (ROOT / "docs/performance/extensions-live.json").write_text(
            json.dumps(public, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(public, ensure_ascii=True))


if __name__ == "__main__":
    run()
