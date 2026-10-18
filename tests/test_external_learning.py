from contextlib import contextmanager
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from pydantic import ValidationError
from app.application.use_cases.workspace import CourseData
from test_extensions_db import db as extensions_db
from test_request_workflow_db import DATABASE_URL, MIGRATIONS, sqlstate
from test_academy import api, COURSE


def content(**changes):
    return dict(
        title="Excel для работы",
        description="Обработка таблиц",
        duration_minutes=0,
        category="Повышение квалификации",
        audience="Все сотрудники",
        passing_score=80,
        material_markdown="",
        quiz=[],
        course_type="external",
        provider="Яндекс Практикум",
        external_url="https://start.practicum.yandex/excel-for-work/",
        **changes,
    )


def test_external_content_has_no_fake_quiz():
    assert CourseData.model_validate(content()).course_type == "external"
    for url in (
        "javascript:alert(1)",
        "http://example.com",
        "https://user:pass@example.com",
        "https://",
    ):
        with pytest.raises(ValidationError):
            CourseData.model_validate({**content(), "external_url": url})
    with pytest.raises(ValidationError):
        CourseData.model_validate({**content(), "course_type": "internal"})


def test_external_progress_accepts_100_but_not_fractions(api):
    client, database, _ = api
    database.tables["courses"][0]["course_type"] = "external"
    assert (
        client.patch(
            f"/api/v1/academy/courses/{COURSE}/progress", json={"progress_percent": 100}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/academy/courses/{COURSE}/progress",
            json={"progress_percent": 50.5},
        ).status_code
        == 422
    )
    assert client.post(f"/api/v1/academy/courses/{COURSE}/enroll").status_code == 200


@pytest.fixture(scope="module")
def external_db():
    if not DATABASE_URL:
        pytest.skip("Set POSTTECH_TEST_DATABASE_URL")
    with contextmanager(extensions_db.__wrapped__)() as database:
        with database.connect(None) as c:
            c.execute(
                (MIGRATIONS / "0014_director_role.sql").read_text(encoding="utf-8")
            )
            c.execute(
                (MIGRATIONS / "0019_external_learning.sql").read_text(encoding="utf-8")
            )
            c.execute(
                (MIGRATIONS / "0020_personal_courses.sql").read_text(encoding="utf-8")
            )
        yield database


def create_course(c, people):
    course_id = str(uuid4())
    row = c.execute(
        "select edit_academy_course(%s,%s,'create',0,%s)",
        (people["hr"], course_id, Jsonb(content())),
    ).fetchone()[0]
    published = c.execute(
        "select edit_academy_course(%s,%s,'publish',%s,'{}')",
        (people["hr"], course_id, row["revision"]),
    ).fetchone()[0]
    assert published["active"] and published["quiz"] == []
    return course_id


def test_external_completion_is_owned_atomic_and_idempotent(external_db):
    db = external_db
    with db.connect() as c:
        course_id = create_course(c, db.people)
        worker = db.people["worker"]
        assignment = c.execute(
            "select enroll_external_course(%s,%s)", (worker, course_id)
        ).fetchone()[0]
        assert (
            c.execute(
                "select enroll_external_course(%s,%s)", (worker, course_id)
            ).fetchone()[0]
            == assignment
        )
        with sqlstate("PT404"):
            c.execute(
                "select update_academy_progress(%s,%s,50)",
                (db.people["outsider"], course_id),
            )
        with sqlstate("PT403"):
            c.execute(
                "select edit_academy_course(%s,%s,'archive',1,'{}')",
                (worker, course_id),
            )
        for percent, expected in (
            (45, 45),
            (20, 45),
            (100, 100),
            (50, 100),
            (100, 100),
        ):
            result = c.execute(
                "select update_academy_progress(%s,%s,%s)", (worker, course_id, percent)
            ).fetchone()[0]
            assert result["progress_percent"] == expected
        assert (
            result["status"] == "completed"
            and result["score_percent"] is None
            and result["completed_at"]
        )
        assert (
            c.execute(
                "select count(*) from course_progress_events where assignment_id=%s",
                (assignment["id"],),
            ).fetchone()[0]
            == 2
        )
        assert (
            c.execute(
                "select count(*) from notifications where course_id=%s", (course_id,)
            ).fetchone()[0]
            == 2
        )
        assert (
            c.execute(
                "select count(*) from course_attempts where assignment_id=%s",
                (assignment["id"],),
            ).fetchone()[0]
            == 0
        )
        with sqlstate("PT422"):
            c.execute("select update_academy_progress(%s,%s,101)", (worker, course_id))


def test_external_versions_archived_assignments_and_seed(external_db):
    db = external_db
    with db.connect() as c:
        course_id = create_course(c, db.people)
        c.execute(
            "select enroll_external_course(%s,%s)", (db.people["worker"], course_id)
        )
        with sqlstate("PT409"):
            c.execute(
                "select edit_academy_course(%s,%s,'save',1,%s)",
                (db.people["hr"], course_id, Jsonb(content())),
            )
        revision = c.execute(
            "select revision from courses where id=%s", (course_id,)
        ).fetchone()[0]
        c.execute(
            "select edit_academy_course(%s,%s,'archive',%s,'{}')",
            (db.people["hr"], course_id, revision),
        )
        with sqlstate("PT404"):
            c.execute(
                "select enroll_external_course(%s,%s)",
                (db.people["outsider"], course_id),
            )
        assert (
            c.execute(
                "select update_academy_progress(%s,%s,35)",
                (db.people["worker"], course_id),
            ).fetchone()[0]["progress_percent"]
            == 35
        )
    with db.connect(None) as c:
        seed = (MIGRATIONS.parent / "seed_external_courses.sql").read_text(
            encoding="utf-8"
        )
        c.execute(seed)
        c.execute(seed)
        assert (
            c.execute(
                "select count(*) from courses where id::text like '42000000-%'"
            ).fetchone()[0]
            == 2
        )


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_external_commands_and_history_are_not_public(external_db, role):
    with external_db.connect(role) as c:
        with sqlstate("42501"):
            c.execute(
                "select enroll_external_course(%s,%s)",
                (external_db.people["worker"], str(uuid4())),
            )
        with sqlstate("42501"):
            c.execute("select * from course_progress_events")


def test_personal_course_http_validation_and_scope(api):
    from app.domain.models import UserContext
    from test_academy import WORKER, OTHER, MANAGER, HR

    client, database, actor = api
    payload = dict(
        id=str(uuid4()),
        title="Мой Excel",
        provider="Яндекс",
        external_url="https://example.com/excel",
        due_on="2027-01-01",
        progress_percent=35,
    )
    assert (
        client.post("/api/v1/academy/personal-courses", json=payload).status_code == 201
    )
    assert database.rpc_calls[-1][1]["p_actor_id"] == WORKER
    for changes in (
        {"progress_percent": 100.5},
        {"progress_percent": 101},
        {"employee_id": OTHER},
        {"due_on": "2026-02-30"},
        {"external_url": "https://user:secret@example.com"},
        {"external_url": "javascript:alert(1)"},
    ):
        assert (
            client.post(
                "/api/v1/academy/personal-courses", json={**payload, **changes}
            ).status_code
            == 422
        )
    database.tables["courses"][0].update(
        owner_employee_id=WORKER, course_type="external"
    )
    database.tables["course_assignments"] = [
        row
        for row in database.tables["course_assignments"]
        if row["employee_id"] == WORKER
    ]
    assert client.get("/api/v1/academy/courses").json() == []
    assert len(client.get("/api/v1/academy/my-courses").json()) == 1
    for role, uid, expected in (
        ("worker", OTHER, 404),
        ("manager", OTHER, 404),
        ("manager", MANAGER, 200),
        ("hr_admin", HR, 200),
    ):
        actor["user"] = UserContext(id=uid, auth_user_id=str(uuid4()), role=role)
        assert client.get(f"/api/v1/academy/courses/{COURSE}").status_code == expected


def test_personal_creation_is_atomic_private_and_retry_safe(external_db):
    db = external_db
    with db.connect() as c:
        course_id = str(uuid4())
        worker = db.people["worker"]
        payload = dict(
            title="Личный курс",
            provider="Практикум",
            external_url="https://example.com/course",
            due_on="2027-02-01",
            progress_percent=35,
        )
        call = lambda actor=worker, data=payload: c.execute(
            "select create_personal_course(%s,%s,%s)", (actor, course_id, Jsonb(data))
        ).fetchone()[0]
        a = call()
        assert a["employee_id"] == worker and a["assigned_by"] == worker
        assert (
            a["due_on"] == "2027-02-01"
            and a["progress_percent"] == 35
            and a["status"] == "in_progress"
        )
        assert call()["id"] == a["id"]
        with sqlstate("PT409"):
            call(data={**payload, "title": "Иное название"})
        with sqlstate("PT409"):
            call(actor=db.people["outsider"])
        with sqlstate("PT403"):
            c.execute(
                "select enroll_external_course(%s,%s)",
                (db.people["outsider"], course_id),
            )
        with sqlstate("PT403"):
            c.execute(
                "insert into course_assignments(course_id,employee_id,assigned_by) values(%s,%s,%s)",
                (course_id, db.people["outsider"], db.people["hr"]),
            )
        c.execute("select update_academy_progress(%s,%s,100)", (worker, course_id))
        assert call()["progress_percent"] == 100
        assert (
            c.execute(
                "select count(*) from course_assignments where course_id=%s",
                (course_id,),
            ).fetchone()[0]
            == 1
        )
        completed_id = str(uuid4())
        result = c.execute(
            "select create_personal_course(%s,%s,%s)",
            (worker, completed_id, Jsonb({**payload, "progress_percent": 100})),
        ).fetchone()[0]
        assert result["status"] == "completed" and result["score_percent"] is None
    with db.connect("authenticated") as c:
        with sqlstate("42501"):
            c.execute(
                "select create_personal_course(%s,%s,%s)",
                (worker, str(uuid4()), Jsonb(payload)),
            )
