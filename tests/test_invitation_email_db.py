from contextlib import contextmanager
from hashlib import sha256

import pytest

from test_registration_db import issue
from test_request_workflow_db import DATABASE_URL, sqlstate
from test_team_workflow_db import team_db, add_person

pytestmark=pytest.mark.skipif(not DATABASE_URL,reason='Local PostgreSQL required')


@pytest.fixture(scope='module')
def email_db():
    # Compile all 18 migrations, including director/two-stage/import overrides.
    with contextmanager(team_db.__wrapped__)() as db:
        yield db


@pytest.mark.parametrize('role',['worker','manager','director','hr_admin'])
def test_send_rotates_and_preserves_role_and_throttles(email_db,role):
    db=email_db
    with db.connect() as c:
        old,inv,details=issue(c,db,role=role)
        digest=sha256(('new-code-'+role).encode()).hexdigest()
        args=(db.people['hr'],inv['id'],digest)
        value=c.execute('select begin_invitation_email(%s,%s,%s)',args).fetchone()[0]
        assert value['email']==details['email'] and value['role']==role
        with sqlstate('PT404'): c.execute('select check_registration_invitation(%s,false)',(old,))
        assert c.execute('select check_registration_invitation(%s,false)',(digest,)).fetchone()[0]['role']==role
        with sqlstate('PT429'): c.execute('select begin_invitation_email(%s,%s,%s)',args)
        # Late response for the previous code cannot change the current status.
        assert c.execute('select finish_invitation_email(%s,%s,%s)',(inv['id'],old,'accepted')).fetchone()[0]['recorded'] is False
        c.execute('select finish_invitation_email(%s,%s,%s)',(inv['id'],digest,'failed'))
        rows=c.execute('select list_registration_invitations(%s)',(db.people['hr'],)).fetchone()[0]
        assert rows[0]['email_status']=='failed'
        assert 'token_hash' not in rows[0]


def test_send_permissions_and_revocation(email_db):
    db=email_db
    with db.connect() as c:
        digest,inv,_=issue(c,db)
        with sqlstate('PT403'):
            c.execute('select begin_invitation_email(%s,%s,%s)',(db.people['manager'],inv['id'],digest))
        c.execute('select revoke_registration_invitation(%s,%s)',(db.people['hr'],inv['id']))
        with sqlstate('PT410'):
            c.execute('select begin_invitation_email(%s,%s,%s)',(db.people['hr'],inv['id'],digest))
    for role in ('anon','authenticated'):
        with db.connect(role) as c:
            with sqlstate('42501'):
                c.execute('select begin_invitation_email(%s,%s,%s)',(db.people['hr'],inv['id'],digest))
            with sqlstate('42501'):
                c.execute('select finish_invitation_email(%s,%s,%s)',(inv['id'],digest,'accepted'))


def test_director_cannot_send_and_director_reporting_line_survives_rotation(email_db):
    db=email_db
    with db.connect(None) as c:
        director=add_person(c,'director')
    with db.connect() as c:
        old,inv,_=issue(c,db,role='manager',manager_id=director)
        digest=sha256(b'director-reporting-line').hexdigest()
        for actor in (director,db.people['manager'],db.people['worker']):
            with sqlstate('PT403'):
                c.execute('select begin_invitation_email(%s,%s,%s)',(actor,inv['id'],digest))
        assert c.execute('select check_registration_invitation(%s,false)',(old,)).fetchone()[0]['role']=='manager'
        c.execute('select begin_invitation_email(%s,%s,%s)',(db.people['hr'],inv['id'],digest))
        c.execute('select finish_invitation_email(%s,%s,%s)',(inv['id'],digest,'accepted'))
    # Extra private columns are inspected by the local fixture owner only.
    with db.connect(None) as c:
        assert c.execute('select manager_id::text,role::text,email_status from registration_invitations where id=%s',
                         (inv['id'],)).fetchone()==(director,'manager','accepted')
