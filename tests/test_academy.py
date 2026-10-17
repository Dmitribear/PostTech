"""Academy HTTP permissions and opt-in isolated PostgreSQL transaction tests."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from postgrest.exceptions import APIError

from app.core.security import get_current_user
from app.main import app
from app.schemas.common import UserContext
from app.services import academy

WORKER, OTHER, MANAGER, HR, COURSE, ASSIGNMENT = [str(UUID(int=i)) for i in range(1, 7)]
NOW = "2026-10-16T12:00:00+00:00"


class Query:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.columns, self.bounds = db, table, [], "*", None

    def select(self, columns): self.columns = columns; return self
    def eq(self, field, value): self.filters.append(lambda row: row.get(field) == value); return self
    def in_(self, field, values): self.filters.append(lambda row: row.get(field) in values); return self
    def order(self, *args, **kwargs): return self
    def limit(self, count): return self.range(0, count - 1)
    def range(self, start, end): self.bounds = start, end + 1; return self

    def execute(self):
        rows = [row for row in self.db.tables[self.table] if all(check(row) for check in self.filters)]
        if self.bounds: rows = rows[slice(*self.bounds)]
        if self.columns != "*": rows = [{key: row.get(key) for key in self.columns.split(',')} for row in rows]
        return SimpleNamespace(data=deepcopy(rows))


class Database:
    def __init__(self):
        assignment = {"id": ASSIGNMENT, "course_id": COURSE, "employee_id": WORKER, "assigned_by": MANAGER,
                      "status": "in_progress", "progress_percent": 90, "score_percent": None, "attempt_count": 0,
                      "material_completed_at": NOW, "last_attempt_at": None, "assigned_at": NOW, "completed_at": None}
        self.tables = {
            "courses": [{"id": COURSE, "title": "Test", "description": "Test", "duration_minutes": 10,
                         "category": "Test", "audience": "All", "passing_score": 80, "active": True, "created_at": NOW,
                         "material_markdown": "# Test", "quiz": [{"id": "q1", "prompt": "Question", "options": ["A", "B"], "answer_index": 1, "private_explanation": "B is correct"}]}],
            "employee_profiles": [{"id": WORKER, "manager_id": MANAGER, "full_name": "Worker"}, {"id": OTHER, "manager_id": None, "full_name": "Other"}],
            "course_assignments": [assignment, {**assignment, "id": str(uuid4()), "employee_id": OTHER}],
            "course_attempts": [{"id": str(uuid4()), "assignment_id": ASSIGNMENT, "attempt_number": 1,
                                 "score_percent": 0, "passed": False, "submitted_at": NOW, "answers": {"q1": 0}, "submission_id": str(uuid4())}],
        }
        self.rpc_calls, self.rpc_error = [], None
        self.rpc_result = assignment

    def table(self, name): return Query(self, name)

    def rpc(self, name, params):
        self.rpc_calls.append((name, params))
        def execute():
            if self.rpc_error: raise self.rpc_error
            return SimpleNamespace(data=deepcopy(self.rpc_result))
        return SimpleNamespace(execute=execute)


@pytest.fixture
def api(monkeypatch):
    database = Database()
    actor = {"user": UserContext(id=WORKER, auth_user_id=str(uuid4()), role="worker")}
    monkeypatch.setattr(academy, "get_supabase_client", lambda: database)
    app.dependency_overrides[get_current_user] = lambda: actor["user"]
    try:
        with TestClient(app) as client: yield client, database, actor
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_catalog_and_attempts_never_expose_answers_or_other_assignment(api):
    client, _, _ = api
    catalog = client.get('/api/v1/academy/courses').json()
    assert catalog[0]['assignment']['employee_id'] == WORKER
    assert 'quiz' not in catalog[0]
    detail = client.get(f'/api/v1/academy/courses/{COURSE}').json()
    assert detail['quiz'] == [{'id': 'q1', 'prompt': 'Question', 'options': ['A', 'B']}]
    attempts = client.get(f'/api/v1/academy/courses/{COURSE}/attempts').json()
    assert len(attempts) == 1
    assert 'answers' not in attempts[0] and 'submission_id' not in attempts[0]


def test_team_scope_and_unassigned_course_permissions(api):
    client, database, actor = api
    assert client.get('/api/v1/academy/team').status_code == 403
    actor['user'] = UserContext(id=MANAGER, auth_user_id=str(uuid4()), role='manager')
    rows = client.get('/api/v1/academy/team').json()
    assert [row['employee_id'] for row in rows] == [WORKER]
    assert client.get(f'/api/v1/academy/team?employee_id={OTHER}').status_code == 403
    assert client.get(f'/api/v1/academy/courses/{COURSE}').status_code == 200
    actor['user'] = UserContext(id=HR, auth_user_id=str(uuid4()), role='hr_admin')
    assert len(client.get('/api/v1/academy/team').json()) == 2
    actor['user'] = UserContext(id=str(uuid4()), auth_user_id=str(uuid4()), role='worker')
    assert client.get(f'/api/v1/academy/courses/{COURSE}').status_code == 403
    assert client.get(f'/api/v1/academy/courses/{COURSE}/attempts').status_code == 404


def test_commands_use_authenticated_actor_and_single_atomic_rpc(api):
    client, db, actor = api
    key = str(uuid4())
    response = client.post(f'/api/v1/academy/courses/{COURSE}/complete', json={'answers': {'q1': 1}}, headers={'Idempotency-Key': key})
    assert response.status_code == 200
    assert db.rpc_calls == [('submit_academy_quiz', {'p_actor_id': WORKER, 'p_course_id': COURSE, 'p_answers': {'q1': 1}, 'p_submission_id': key})]
    assert client.post('/api/v1/academy/assignments', json={'employee_id': OTHER, 'course_id': COURSE}).status_code == 403
    actor['user'] = UserContext(id=MANAGER, auth_user_id=str(uuid4()), role='manager')
    assert client.post('/api/v1/academy/assignments', json={'employee_id': WORKER, 'course_id': COURSE}).status_code == 201
    assert db.rpc_calls[-1][0] == 'assign_academy_course'


@pytest.mark.parametrize('payload', [{'answers': {'q1': True}}, {'answers': {'q1': '1'}}, {'answers': {}}, {'answers': {'q1': 1}, 'score_percent': 100}])
def test_quiz_rejects_invalid_or_forged_answers_before_database(api, payload):
    client, db, _ = api
    assert client.post(f'/api/v1/academy/courses/{COURSE}/complete', json=payload).status_code == 422
    assert not db.rpc_calls


@pytest.mark.parametrize('payload', [{'progress_percent': 100}, {'progress_percent': -1}, {'progress_percent': True}, {'progress_percent': 90, 'status': 'completed'}])
def test_progress_rejects_spoofing(api, payload):
    client, db, _ = api
    assert client.patch(f'/api/v1/academy/courses/{COURSE}/progress', json=payload).status_code == 422
    assert not db.rpc_calls


@pytest.mark.parametrize('code,status', [('PT403', 403), ('PT409', 409), ('PT422', 422), ('PGRST202', 503), ('XX000', 503)])
def test_rpc_errors_have_safe_http_status(api, code, status):
    client, db, _ = api
    db.rpc_error = APIError({'code': code, 'message': 'Synthetic failure', 'details': None, 'hint': None})
    response = client.patch(f'/api/v1/academy/courses/{COURSE}/progress', json={'progress_percent': 90})
    assert response.status_code == status
    if status == 503: assert 'Synthetic failure' not in response.text


@pytest.fixture(scope='module')
def academy_db():
    url = os.environ.get('POSTTECH_TEST_DATABASE_URL')
    if not url: pytest.skip('Set POSTTECH_TEST_DATABASE_URL for real PostgreSQL academy tests')
    psycopg = pytest.importorskip('psycopg')
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    assert conninfo_to_dict(url).get('dbname', '').startswith('posttech_test_'), 'Use an empty local test control database'
    name = 'posttech_test_academy_' + uuid4().hex
    dsn = make_conninfo(url, dbname=name)
    people = {name: str(uuid4()) for name in ('manager', 'other_manager', 'hr', 'worker', 'outsider')}
    migrations = Path(__file__).resolve().parents[1] / 'database' / 'migrations'
    with psycopg.connect(url, autocommit=True) as admin:
        assert admin.execute("select to_regclass('public.employee_profiles')").fetchone()[0] is None
        for role in ('anon', 'authenticated', 'service_role'):
            if admin.execute('select 1 from pg_roles where rolname=%s', (role,)).fetchone() is None:
                admin.execute(sql.SQL('create role {} nologin {}').format(sql.Identifier(role), sql.SQL('bypassrls' if role == 'service_role' else 'nobypassrls')))
        admin.execute(sql.SQL('create database {}').format(sql.Identifier(name)))
        try:
            with psycopg.connect(dsn, autocommit=True) as setup:
                setup.execute('create schema auth; create table auth.users(id uuid primary key, email text)')
                setup.execute((migrations / '0001_digital_hr.sql').read_text(encoding='utf-8'))
                setup.execute((migrations / '0004_academy_workflow.sql').read_text(encoding='utf-8'))
                for person, person_id in people.items():
                    role = 'hr_admin' if person == 'hr' else 'manager' if 'manager' in person else 'worker'
                    manager = people['manager'] if person == 'worker' else people['other_manager'] if person == 'outsider' else None
                    setup.execute('insert into auth.users(id,email) values (%s,%s)', (person_id, person+'@example.test'))
                    setup.execute("insert into employee_profiles(id,auth_user_id,employee_code,full_name,email,company,job_title,department,manager_id,hired_at,role) values(%s,%s,%s,%s,%s,'Test','Test','Test',%s,'2026-01-01',%s)", (person_id,person_id,person,person,person+'@example.test',manager,role))
                setup.execute("""create function test_notification_failure() returns trigger language plpgsql as $$
                begin if current_setting('posttech_test.fail_notifications', true)='on' then raise exception 'Forced failure'; end if; return new; end; $$;
                create trigger fail_test_notification before insert on notifications for each row execute function test_notification_failure();""")
            @contextmanager
            def connect(role='service_role'):
                with psycopg.connect(dsn, autocommit=True) as connection:
                    connection.execute("set statement_timeout='15s'; set lock_timeout='10s'")
                    if role: connection.execute(sql.SQL('set role {}').format(sql.Identifier(role)))
                    yield connection
            yield SimpleNamespace(connect=connect, people=people)
        finally:
            admin.execute(sql.SQL('drop database {} with(force)').format(sql.Identifier(name)))


def new_course(db, assign=True):
    course = str(uuid4())
    with db.connect(None) as connection:
        connection.execute("""insert into courses(id,title,description,duration_minutes,material_markdown,quiz)
        values(%s,'Test course','Test',10,'# Read me','[{"id":"q1","prompt":"First","options":["A","B"],"answer_index":0},{"id":"q2","prompt":"Second","options":["A","B"],"answer_index":1}]')""", (course,))
    if assign:
        with db.connect() as connection: assign_sql(connection, db.people['manager'], db.people['worker'], course)
    return course


def assign_sql(connection, actor, employee, course):
    return connection.execute('select assign_academy_course(%s,%s,%s)', (actor,employee,course)).fetchone()[0]


def progress_sql(connection, actor, course, percent=90):
    return connection.execute('select update_academy_progress(%s,%s,%s)', (actor,course,percent)).fetchone()[0]


def quiz_sql(connection, actor, course, answers=None, key=None):
    from psycopg.types.json import Jsonb
    return connection.execute('select submit_academy_quiz(%s,%s,%s,%s)', (actor,course,Jsonb(answers if answers is not None else {'q1':0,'q2':1}),key or str(uuid4()))).fetchone()[0]


def test_sql_failed_attempt_replay_retry_and_stable_completion(academy_db):
    db=academy_db; course=new_course(db); actor=db.people['worker']; key=str(uuid4())
    with db.connect() as connection:
        with pytest.raises(Exception, match='Read the course material'): quiz_sql(connection,actor,course)
        progress_sql(connection,actor,course)
        failed=quiz_sql(connection,actor,course,{'q1':1,'q2':0},key)
        assert failed['status']=='in_progress' and failed['score_percent']==0 and failed['attempt_count']==1
        assert failed['completed_at'] is None and failed['progress_percent']==90
        assert quiz_sql(connection,actor,course,{'q1':1,'q2':0},key)==failed
        with pytest.raises(Exception, match='different answers'): quiz_sql(connection,actor,course,{'q1':0,'q2':1},key)
        completed=quiz_sql(connection,actor,course)
        assert completed['status']=='completed' and completed['score_percent']==100 and completed['attempt_count']==2
        assert quiz_sql(connection,actor,course,{'q1':1,'q2':0})==completed
        assert progress_sql(connection,actor,course,0)==completed
        assert connection.execute('select count(*) from course_attempts where assignment_id=%s',(completed['id'],)).fetchone()[0]==2
        recipients=connection.execute("select employee_id::text from notifications where course_id=%s and notification_type like '%%completed' order by employee_id",(course,)).fetchall()
        assert {row[0] for row in recipients}=={actor,db.people['manager']}


def test_sql_rights_and_atomic_notification_rollback(academy_db):
    db=academy_db; course=new_course(db,False)
    with db.connect() as connection:
        for actor,employee in [(db.people['worker'],db.people['worker']),(db.people['manager'],db.people['outsider'])]:
            with pytest.raises(Exception) as error: assign_sql(connection,actor,employee,course)
            assert error.value.sqlstate=='PT403'
        connection.execute("set posttech_test.fail_notifications='on'")
        with pytest.raises(Exception,match='Forced failure'): assign_sql(connection,db.people['manager'],db.people['worker'],course)
        assert connection.execute('select count(*) from course_assignments where course_id=%s',(course,)).fetchone()[0]==0
        connection.execute("set posttech_test.fail_notifications='off'")
        assigned=assign_sql(connection,db.people['manager'],db.people['worker'],course)
        with pytest.raises(Exception) as error: quiz_sql(connection,db.people['outsider'],course)
        assert error.value.sqlstate=='PT404'
        with pytest.raises(Exception,match='already assigned'): assign_sql(connection,db.people['manager'],db.people['worker'],course)
        progress_sql(connection,db.people['worker'],course)
        connection.execute("set posttech_test.fail_notifications='on'")
        with pytest.raises(Exception,match='Forced failure'): quiz_sql(connection,db.people['worker'],course)
        assert connection.execute('select attempt_count,status::text from course_assignments where id=%s',(assigned['id'],)).fetchone()==(0,'in_progress')
        assert connection.execute('select count(*) from course_attempts where assignment_id=%s',(assigned['id'],)).fetchone()[0]==0
        connection.execute("set posttech_test.fail_notifications='off'")
        assert quiz_sql(connection,db.people['worker'],course)['status']=='completed'


def test_sql_concurrent_quiz_progress_and_duplicate_assignment(academy_db):
    db=academy_db; course=new_course(db,False); barrier=Barrier(2)
    def assign():
        with db.connect() as connection:
            barrier.wait()
            try: return assign_sql(connection,db.people['manager'],db.people['worker'],course)['id']
            except Exception as exc: return exc.sqlstate
    with ThreadPoolExecutor(max_workers=2) as pool: assigned=list(pool.map(lambda _:assign(),range(2)))
    assert assigned.count('PT409')==1
    with db.connect() as connection: progress_sql(connection,db.people['worker'],course)
    barrier=Barrier(3)
    def change(index):
        with db.connect() as connection:
            barrier.wait()
            return progress_sql(connection,db.people['worker'],course,10) if index==0 else quiz_sql(connection,db.people['worker'],course)
    with ThreadPoolExecutor(max_workers=3) as pool: list(pool.map(change,range(3)))
    with db.connect() as connection:
        final=progress_sql(connection,db.people['worker'],course,0)
        assert final['status']=='completed' and final['progress_percent']==100 and final['attempt_count']==1
        assert connection.execute('select count(*) from notifications where course_id=%s',(course,)).fetchone()[0]==3


@pytest.mark.parametrize('role',['anon','authenticated'])
def test_sql_public_clients_cannot_execute_commands_or_read_answers(academy_db,role):
    with academy_db.connect(role) as connection:
        with pytest.raises(Exception) as error: quiz_sql(connection,academy_db.people['worker'],str(uuid4()))
        assert error.value.sqlstate=='42501'
        with pytest.raises(Exception) as error: connection.execute('select * from course_attempts')
        assert error.value.sqlstate=='42501'


@pytest.mark.parametrize('threshold,passed', [(50, True), (80, False)])
def test_sql_uses_configured_passing_score_and_preserves_material_progress(academy_db, threshold, passed):
    db = academy_db
    course = new_course(db)
    with db.connect(None) as connection:
        connection.execute('update courses set passing_score=%s where id=%s', (threshold, course))
    with db.connect() as connection:
        actor = db.people['worker']
        marked = progress_sql(connection, actor, course, 95)
        lower = progress_sql(connection, actor, course, 20)
        assert lower['progress_percent'] == 95
        assert lower['material_completed_at'] == marked['material_completed_at']
        result = quiz_sql(connection, actor, course, {'q1': 0, 'q2': 0})
        assert result['score_percent'] == 50
        assert (result['status'] == 'completed') is passed
        assert result['progress_percent'] == (100 if passed else 95)


def test_sql_invalid_manager_does_not_receive_completion_data(academy_db):
    db = academy_db
    course = new_course(db)
    with db.connect(None) as connection:
        connection.execute('update employee_profiles set manager_id=%s where id=%s', (db.people['outsider'], db.people['worker']))
    try:
        with db.connect() as connection:
            progress_sql(connection, db.people['worker'], course)
            quiz_sql(connection, db.people['worker'], course)
            recipients = connection.execute("select employee_id::text from notifications where course_id=%s and notification_type like '%%completed'", (course,)).fetchall()
            assert recipients == [(db.people['worker'],)]
    finally:
        with db.connect(None) as connection:
            connection.execute('update employee_profiles set manager_id=%s where id=%s', (db.people['manager'], db.people['worker']))


def test_sql_failed_submission_is_idempotent_under_concurrency(academy_db):
    db = academy_db
    course = new_course(db)
    key = str(uuid4())
    with db.connect() as connection:
        progress_sql(connection, db.people['worker'], course)
    barrier = Barrier(2)
    def submit():
        with db.connect() as connection:
            barrier.wait()
            return quiz_sql(connection, db.people['worker'], course, {'q1': 1, 'q2': 0}, key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit(), range(2)))
    assert results[0] == results[1]
    assert results[0]['attempt_count'] == 1 and results[0]['status'] == 'in_progress'


@pytest.mark.parametrize('answers', [{'q1': 0}, {'q1': 0, 'q2': 1, 'extra': 0}, {'q1': -1, 'q2': 1}, {'q1': True, 'q2': 1}, {'q1': 99, 'q2': 1}])
def test_sql_rejects_invalid_answers_even_without_api(academy_db, answers):
    db = academy_db
    course = new_course(db)
    with db.connect() as connection:
        assigned = progress_sql(connection, db.people['worker'], course)
        with pytest.raises(Exception) as error:
            quiz_sql(connection, db.people['worker'], course, answers)
        assert error.value.sqlstate == 'PT422'
        assert connection.execute('select count(*) from course_attempts where assignment_id=%s', (assigned['id'],)).fetchone()[0] == 0


def test_sql_hr_can_assign_other_team_and_demo_seed_is_repeatable(academy_db):
    db = academy_db
    course = new_course(db, False)
    with db.connect() as connection:
        assert assign_sql(connection, db.people['hr'], db.people['outsider'], course)['employee_id'] == db.people['outsider']
    seed = Path(__file__).resolve().parents[1] / 'database' / 'seed_academy_demo.sql'
    with db.connect(None) as connection:
        connection.execute(seed.read_text(encoding='utf-8'))
        connection.execute("update courses set title='Preserved custom title' where id='41000000-0000-4000-8000-000000000001'")
        connection.execute(seed.read_text(encoding='utf-8'))
        assert connection.execute("select count(*) from courses where id::text like '41000000-%%'").fetchone()[0] == 3
        assert connection.execute("select title from courses where id='41000000-0000-4000-8000-000000000001'").fetchone()[0] == 'Preserved custom title'
