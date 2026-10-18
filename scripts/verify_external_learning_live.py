"""Exercise external learning only with the marked fictional jury profiles."""

from datetime import date, timedelta
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_live_workflow import (
    API,
    ROOT,
    read_json,
    require,
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
        session = api.call(
            "POST", "/auth/login", body={k: account[k] for k in ("email", "password")}
        )
        api.tokens[role] = session["access_token"]
        profiles[role] = api.call("GET", "/profile", role)
        require(
            profiles[role]["external_source"] == "posttech-jury-fixture"
            and profiles[role]["id"] == account["profile_id"],
            "Synthetic marker missing",
        )
    checkpoint = ROOT / ".local/external-learning-live.json"
    with checkpoint_lock(checkpoint):
        state = (
            read_json(checkpoint)
            if checkpoint.exists()
            else {"fixture_id": credentials["fixture_id"], "course": str(uuid4())}
        )
        require(state["fixture_id"] == credentials["fixture_id"], "Checkpoint mismatch")
        save_checkpoint(checkpoint, state)
        course_id = state["course"]
        catalog = api.call("GET", "/academy/courses", "employee")
        require(
            len([c for c in catalog if c.get("course_type") == "external"]) >= 2,
            "External catalog missing",
        )
        course = api.call(
            "POST",
            "/workspace/courses",
            "hr",
            body={
                "id": course_id,
                "action": "create",
                "data": {
                    "title": "Проверка внешнего обучения · тестовый аккаунт",
                    "description": "Техническая проверка. Не является результатом реального обучения.",
                    "course_type": "external",
                    "provider": "Яндекс Практикум",
                    "external_url": "https://start.practicum.yandex/excel-for-work/",
                    "duration_minutes": 0,
                    "material_markdown": "",
                    "quiz": [],
                    "passing_score": 80,
                    "category": "Проверка",
                    "audience": "Тестовые аккаунты",
                },
            },
        )
        if course["publication_state"] == "archived" and state.get("completed"):
            print(
                "External learning live check was already completed; checkpoint preserved."
            )
            return
        if course["publication_state"] == "draft":
            course = api.call(
                "POST",
                "/workspace/courses",
                "hr",
                body={
                    "id": course_id,
                    "action": "publish",
                    "revision": course["revision"],
                },
            )
        assignment = api.call(
            "POST", f"/academy/courses/{course_id}/enroll", "employee"
        )
        repeated = api.call("POST", f"/academy/courses/{course_id}/enroll", "employee")
        require(assignment["id"] == repeated["id"], "Duplicate self enrollment")
        due = (date.today() + timedelta(days=10)).isoformat()
        api.call(
            "PATCH",
            f"/workspace/assignments/{assignment['id']}/deadline",
            "manager",
            body={"due_on": due},
        )
        api.call("GET", "/academy/team", "employee", expected=403)
        api.call(
            "PATCH",
            f"/academy/courses/{course_id}/progress",
            "manager",
            body={"progress_percent": 50},
            expected=404,
        )
        for percent in (55, 100):
            result = api.call(
                "PATCH",
                f"/academy/courses/{course_id}/progress",
                "employee",
                body={"progress_percent": percent},
            )
            require(
                result["progress_percent"] >= percent
                and result["score_percent"] is None,
                "Unexpected external result",
            )
            for role in ("manager", "hr"):
                rows = api.call(
                    "GET",
                    f"/academy/team?employee_id={profiles['employee']['id']}&course_id={course_id}",
                    role,
                )
                require(
                    len(rows) == 1
                    and rows[0]["progress_percent"] == result["progress_percent"]
                    and rows[0]["due_on"] == due,
                    "Team progress or deadline mismatch",
                )
            if percent == 55 and "--prepare" in sys.argv:
                state.update(due_on=due, ready=True)
                save_checkpoint(checkpoint, state)
                print("External learning fixture ready for UI verification.")
                return
        api.call(
            "PATCH",
            f"/academy/courses/{course_id}/progress",
            "employee",
            body={"progress_percent": 100},
        )
        require(
            result["status"] == "completed" and result["completed_at"],
            "Completion missing",
        )
        for role in ("employee", "manager"):
            notices = api.rows("/notifications", role)
            require(
                len(
                    [
                        n
                        for n in notices
                        if n.get("course_id") == course_id
                        and n["notification_type"].endswith("completed")
                    ]
                )
                == 1,
                "Missing or duplicate completion notification",
            )
        require(
            api.call("GET", f"/academy/courses/{course_id}/attempts", "employee") == [],
            "External course should not fabricate quiz attempts",
        )
        api.call(
            "POST",
            "/workspace/courses",
            "hr",
            body={"id": course_id, "action": "archive", "revision": course["revision"]},
        )
        state.update(
            completed=True, checked_at=now(), api_calls=api.calls, result="passed"
        )
        save_checkpoint(checkpoint, state)
        print(
            json.dumps(
                {
                    "result": "passed",
                    "api_calls": api.calls,
                    "roles": ["employee", "manager", "hr"],
                    "test_course": "archived",
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    run()
