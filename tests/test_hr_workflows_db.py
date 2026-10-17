from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from hashlib import sha256
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb
from test_request_workflow_db import DATABASE_URL, MIGRATIONS, db as legacy_db, sqlstate, create_request, review_request

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason='Set POSTTECH_TEST_DATABASE_URL')


@pytest.fixture(scope='module')
def db():
    with contextmanager(legacy_db.__wrapped__)() as database:
        with database.connect(None) as c:
            c.execute('alter table auth.users add column email_confirmed_at timestamptz')
            for number in range(3,13):
                c.execute(next(MIGRATIONS.glob(f'{number:04d}*.sql')).read_text(encoding='utf-8'))
        yield database


def advance(c, db, actor=None):
    return create_request(c, actor or db.people['worker'],request_type='advance',start_date=None,end_date=None,amount=1000)


def fulfill(c, db, request_id, action='complete', ref='Order-123', actor=None):
    return c.execute('select fulfill_hr_request(%s,%s,%s,%s,%s)',(actor or db.people['hr'],request_id,action,ref,'')).fetchone()[0]


def course(c, title):
    return str(c.execute("insert into courses(title,description,duration_minutes,material_markdown,quiz) values(%s,'Test',5,'Material','[]') returning id",(title,)).fetchone()[0])


def test_approval_waits_for_hr_and_manual_fulfillment_is_idempotent(db):
    with db.connect() as c:
        r=advance(c,db)
        with sqlstate('PT409'): fulfill(c,db,r['id'])
        review_request(c,db.people['manager'],r['id'])
        assert c.execute('select status from request_fulfillment where request_id=%s',(r['id'],)).fetchone()[0]=='awaiting_hr'
        assert c.execute('select count(*) from integration_outbox where aggregate_id=%s',(r['id'],)).fetchone()[0]==0
        with sqlstate('PT403'): fulfill(c,db,r['id'],actor=db.people['manager'])
        with sqlstate('PT422'): fulfill(c,db,r['id'],ref='')
        first=fulfill(c,db,r['id']); assert first['status']=='completed'
        assert fulfill(c,db,r['id'])==first
        with sqlstate('PT409'): fulfill(c,db,r['id'],ref='Different-Document')
        assert c.execute("select count(*) from fulfillment_events where request_id=%s and action='complete'",(r['id'],)).fetchone()[0]==1


def test_hr_cannot_fulfill_their_own_request(db):
    with db.connect(None) as c:
        c.execute('update employee_profiles set manager_id=%s where id=%s',(db.people['manager'],db.people['hr']))
        r=advance(c,db,db.people['hr'])
    with db.connect(None) as c:
        c.execute("update hr_requests set status='approved' where id=%s",(r['id'],))
    with db.connect() as c:
        with sqlstate('PT403'): fulfill(c,db,r['id'])


def test_delivery_ack_does_not_complete_document_and_ambiguous_event_blocks_manual(db):
    with db.connect() as c:
        r=advance(c,db);review_request(c,db.people['manager'],r['id'])
        for _ in range(2): fulfill(c,db,r['id'],'start')
        assert c.execute('select count(*) from integration_outbox where aggregate_id=%s',(r['id'],)).fetchone()[0]==2
        event=c.execute("select claim_integration_event('1c')").fetchone()[0]
        with sqlstate('PT409'):fulfill(c,db,r['id'])
        c.execute('select finish_integration_event(%s,%s,true)',(event['id'],event['lease_token']))
        with sqlstate('PT409'):fulfill(c,db,r['id'])
        event=c.execute("select claim_integration_event('documentolog')").fetchone()[0]
        c.execute('select finish_integration_event(%s,%s,true)',(event['id'],event['lease_token']))
        assert c.execute('select status from request_fulfillment where request_id=%s',(r['id'],)).fetchone()[0]=='processing'
        assert fulfill(c,db,r['id'])['status']=='completed'


def test_manual_replaces_only_never_attempted_events(db):
    with db.connect() as c:
        r=advance(c,db);review_request(c,db.people['manager'],r['id']);fulfill(c,db,r['id'],'start')
        fulfill(c,db,r['id'])
        assert c.execute('select distinct status from integration_outbox where aggregate_id=%s',(r['id'],)).fetchall()==[('cancelled',)]


def test_track_unlocks_in_order_preserves_deadline_and_enrollment_is_idempotent(db):
    p=db.people;track=uuid4()
    with db.connect(None) as c:
        first,second=course(c,'First track course'),course(c,'Second track course')
        steps=Jsonb([{'course_id':first,'days_to_complete':2},{'course_id':second,'days_to_complete':5}])
        with sqlstate('PT403'): c.execute('select create_learning_track(%s,%s,%s,%s)',(p['worker'],track,'Onboarding',steps))
        c.execute('select create_learning_track(%s,%s,%s,%s)',(p['hr'],track,'Onboarding',steps))
        for _ in range(2): c.execute('select enroll_learning_track(%s,%s,%s)',(p['hr'],track,p['worker']))
        assert c.execute('select course_id::text from course_assignments where employee_id=%s',(p['worker'],)).fetchall()==[(first,)]
        with sqlstate('PT404'):c.execute('select update_academy_progress(%s,%s,90)',(p['worker'],second))
        c.execute("update course_assignments set status='completed',progress_percent=100 where employee_id=%s and course_id=%s",(p['worker'],first))
        c.execute('select advance_learning_tracks(%s)',(p['worker'],))
        assert c.execute('select due_on from course_assignments where employee_id=%s and course_id=%s',(p['worker'],second)).fetchone()[0]==date.today()+timedelta(days=5)
        c.execute("update course_assignments set status='completed',progress_percent=100 where employee_id=%s and course_id=%s",(p['worker'],second))
        c.execute('select advance_learning_tracks(%s)',(p['worker'],))
        assert c.execute('select completed_at is not null from learning_enrollments where track_id=%s',(track,)).fetchone()[0]


def test_new_hire_gets_auto_track_and_archiving_keeps_existing_plan(db):
    p=db.people; track=uuid4();auth=uuid4();employee=uuid4()
    with db.connect(None) as c:
        first=course(c,'Automatic onboarding')
        c.execute('select create_learning_track(%s,%s,%s,%s,%s)',(p['hr'],track,'New warehouse employee',Jsonb([{'course_id':first,'days_to_complete':4}]),'worker'))
    with db.connect(None) as c:
        c.execute('insert into auth.users(id,email) values(%s,%s)',(auth,'onboard@example.test'))
        c.execute("insert into employee_profiles(id,auth_user_id,employee_code,full_name,email,company,job_title,department,hired_at) values(%s,%s,'ONBOARD','New Hire','onboard@example.test','PostTech','Worker','Warehouse',current_date)",(employee,auth))
    with db.connect() as c:
        assert c.execute('select count(*) from course_assignments where employee_id=%s',(employee,)).fetchone()[0]==1
        c.execute('update learning_tracks set active=false,auto_role=null where id=%s',(track,))
        assert c.execute('select count(*) from learning_enrollments where employee_id=%s',(employee,)).fetchone()[0]==1
        with sqlstate('PT404'):c.execute('select enroll_learning_track(%s,%s,%s)',(p['hr'],track,p['outsider']))


def test_service_role_can_enroll_and_unavailable_manager_escalates_early(db):
    p=db.people;track=uuid4()
    with db.connect(None) as c:
        first=course(c,'Service role learning')
    with db.connect() as c:
        c.execute('select create_learning_track(%s,%s,%s,%s)',(p['hr'],track,'Service track',Jsonb([{'course_id':first,'days_to_complete':3}])))
        result=c.execute('select enroll_learning_track(%s,%s,%s)',(p['hr'],track,p['outsider'])).fetchone()[0]
        assert result['employee_id']==p['outsider']
        leave=create_request(c,p['other_manager'],start_date=date.today(),end_date=date.today())
        review_request(c,p['hr'],leave['id'])
        request=advance(c,db,p['outsider'])
        c.execute('select run_workflow_reminders()')
        assert c.execute("select count(*) from notifications where request_id=%s and employee_id=%s and notification_type='workflow_reminder'",(request['id'],p['hr'])).fetchone()[0]==1
        review_request(c,p['hr'],request['id'],'rejected','test cleanup')


def test_reminder_cycles_are_deduplicated_and_escalate_without_approving(db):
    p=db.people
    with db.connect(None) as c:
        r=advance(c,db)
        c.execute("update hr_requests set created_at=now()-interval '5 days' where id=%s",(r['id'],))
        def run(_):
            with db.connect() as other:return other.execute('select run_workflow_reminders()').fetchone()[0]
        with ThreadPoolExecutor(2) as pool:list(pool.map(run,[0,1]))
        assert c.execute('select status from hr_requests where id=%s',(r['id'],)).fetchone()[0]=='pending'
        reminders=c.execute("select employee_id::text from notifications where request_id=%s and notification_type='workflow_reminder'",(r['id'],)).fetchall()
        assert sorted(x[0] for x in reminders)==sorted([p['hr'],p['manager']])
        c.execute('select run_workflow_reminders()')
        assert c.execute("select count(*) from notifications where request_id=%s and notification_type='workflow_reminder'",(r['id'],)).fetchone()[0]==2
        review_request(c,p['manager'],r['id'],'rejected','test cleanup')


def test_import_rolls_back_all_rows_if_preview_stale_and_never_changes_access(db):
    p=db.people
    with db.connect(None) as c:
        row=c.execute('select to_jsonb(e) from employee_profiles e where id=%s',(p['worker'],)).fetchone()[0]
        batch=uuid4();new_code=uuid4().hex
        existing={**row,'profile_id':row['id'],'expected_updated_at':row['updated_at'],'action':'update','full_name':'Updated Name'}
        new={**row,'employee_code':new_code,'email':new_code+'@example.test','action':'invite','role':'worker'}
        c.execute('insert into employee_imports(id,created_by,filename,rows,errors) values(%s,%s,%s,%s,%s)',(batch,p['hr'],'test.csv',Jsonb([new,existing]),Jsonb([])))
        c.execute("update employee_profiles set full_name='Concurrent Change' where id=%s",(p['worker'],))
        with sqlstate('PT409'): c.execute('select apply_employee_import(%s,%s,%s)',(p['hr'],batch,Jsonb({new_code:sha256(b'test-import').hexdigest()})))
        assert c.execute('select count(*) from registration_invitations where employee_code=%s',(new_code,)).fetchone()[0]==0


def test_import_invites_without_fake_auth_and_repeat_does_not_create_more(db):
    p=db.people;batch=uuid4();code=uuid4().hex
    row=dict(employee_code=code,email=code+'@example.test',company='PostTech',job_title='Worker',department='Warehouse',hired_at='2026-10-17',role='worker',action='invite',manager_id=p['manager'])
    with db.connect() as c:
        c.execute('insert into employee_imports(id,created_by,filename,rows,errors) values(%s,%s,%s,%s,%s)',(batch,p['hr'],'test.csv',Jsonb([row]),Jsonb([])))
        args=(p['hr'],batch,Jsonb({code:sha256(b'import-test').hexdigest()}))
        result=c.execute('select apply_employee_import(%s,%s,%s)',args).fetchone()[0]
        assert len(result['invitations'])==1
        assert c.execute('select apply_employee_import(%s,%s,%s)',args).fetchone()[0]['already_applied']
        assert c.execute('select count(*) from employee_profiles where employee_code=%s',(code,)).fetchone()[0]==0


@pytest.mark.parametrize('role',['anon','authenticated'])
def test_browser_cannot_read_or_execute_workflows(db,role):
    with db.connect(role) as c:
        for table in ('employee_imports','request_fulfillment','learning_enrollments','workflow_policy','workflow_reminders'):
            with sqlstate('42501'):c.execute('select * from '+table)
        with sqlstate('42501'):c.execute('select run_workflow_reminders()')
        with sqlstate('42501'):c.execute('select advance_learning_tracks()')
