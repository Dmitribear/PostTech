"""Telegram identity, notification delivery and permission boundaries in real SQL."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from uuid import uuid4

import pytest

from test_request_workflow_db import DATABASE_URL, sqlstate
from test_team_workflow_db import team_db, add_person

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="Local disposable PostgreSQL required")


@pytest.fixture
def person(team_db):
    with team_db.connect(None) as c:
        return add_person(c)


def issue(c, person):
    digest = sha256(uuid4().bytes).hexdigest()
    result = c.execute("select issue_telegram_link(%s,%s)",(person,digest)).fetchone()[0]
    return digest,result


def consume(c, digest, user=12345):
    return c.execute("select consume_telegram_link(%s,%s,%s,'alice')",(digest,user,user)).fetchone()[0]


def notify(c, person):
    return c.execute("insert into notifications(employee_id,title,body,notification_type) values(%s,'Title','Body','test') returning id",(person,)).fetchone()[0]


def link(db,person):
    user = int(uuid4().hex[:12],16)
    with db.connect() as c:
        digest,_ = issue(c,person)
        consume(c,digest,user)
    return user


def test_one_use_expiry_rotation_and_unlink(team_db,person):
    user = int(uuid4().hex[:12],16)
    with team_db.connect() as c:
        old,_ = issue(c,person)
        new,expiry = issue(c,person)
        with sqlstate('PT410'): consume(c,old,user)
        assert consume(c,new,user)['employee_id'] == person
        with sqlstate('PT410'): consume(c,new,user)
        with sqlstate('PT409'): issue(c,person)
        assert c.execute('select resolve_telegram_actor(%s)',(user,)).fetchone()[0]['id'] == person
        c.execute('select unlink_telegram(%s)',(person,))
        with sqlstate('PT403'): c.execute('select resolve_telegram_actor(%s)',(user,))
        with sqlstate('PT410'): consume(c,new,user)
        expired,_=issue(c,person)
    with team_db.connect(None) as c:
        c.execute("update telegram_link_codes set expires_at=now()-interval '1 second' where employee_id=%s",(person,))
    with team_db.connect() as c:
        with sqlstate('PT410'): consume(c,expired,user)
        revoked,_=issue(c,person)
        c.execute('select unlink_telegram(%s)',(person,))
        with sqlstate('PT410'): consume(c,revoked,user)


def test_identity_cannot_rebind_and_current_role_is_used(team_db,person):
    user=link(team_db,person)
    with team_db.connect(None) as c:
        other=add_person(c)
        c.execute("update employee_profiles set role='director' where id=%s",(person,))
    with team_db.connect() as c:
        code,_=issue(c,other)
        with sqlstate('PT409'): consume(c,code,user)
        assert c.execute('select resolve_telegram_actor(%s)',(user,)).fetchone()[0]['role'] == 'director'
        assert c.execute('select telegram_status(%s)',(other,)).fetchone()[0]['linked'] is False
        with sqlstate('PT422'):
            c.execute("select consume_telegram_link(%s,%s,%s,null)",(code,user,-user))


def test_concurrent_consumption_only_once(team_db,person):
    with team_db.connect() as c: code,_=issue(c,person)
    def run(user):
        import psycopg
        try:
            with team_db.connect() as c: return consume(c,code,user)['linked']
        except psycopg.Error as e: return e.sqlstate
    base=int(uuid4().hex[:12],16)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(run,(base,base+1)))
    assert results.count(True)==1 and results.count('PT410')==1


def test_new_notifications_only_leases_and_retry(team_db,person):
    with team_db.connect() as c: notify(c,person)
    user=link(team_db,person)
    with team_db.connect() as c:
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0] == []
        notification=notify(c,person)
        rows=c.execute('select claim_telegram_outbox(100)').fetchone()[0]
        row=next(r for r in rows if r['notification_id']==str(notification))
        assert row['telegram_user_id']==user and row['chat_id']==user and row['body']=='Body'
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]
        assert c.execute("select ack_telegram_outbox(%s,%s,'sent',30)",(row['id'],str(uuid4()))).fetchone()[0]['recorded'] is False
        assert c.execute("select ack_telegram_outbox(%s,%s,'retry',45)",(row['id'],row['lease_token'])).fetchone()[0]['recorded'] is True
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]
    with team_db.connect(None) as c:
        c.execute("update telegram_outbox set available_at=now()-interval '1 second' where id=%s",(row['id'],))
    with team_db.connect() as c:
        second=c.execute('select claim_telegram_outbox(100)').fetchone()[0][0]
        assert second['lease_token']!=row['lease_token'] and second['attempts']==2
        assert c.execute("select ack_telegram_outbox(%s,%s,'sent',30)",(row['id'],row['lease_token'])).fetchone()[0]['recorded'] is False
        assert c.execute("select ack_telegram_outbox(%s,%s,'sent',30)",(second['id'],second['lease_token'])).fetchone()[0]['recorded'] is True
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]


def test_disabled_unlinked_blocked_and_lease_expiry(team_db,person):
    user=link(team_db,person)
    with team_db.connect() as c:
        notify(c,person)
        row=c.execute('select claim_telegram_outbox(100)').fetchone()[0][0]
    with team_db.connect(None) as c:
        c.execute("update telegram_outbox set lease_until=now()-interval '1 second' where id=%s",(row['id'],))
    with team_db.connect() as c:
        retry=c.execute('select claim_telegram_outbox(100)').fetchone()[0][0]
        assert retry['attempts']==2 and retry['lease_token']!=row['lease_token']
        notify(c,person)
        c.execute("select ack_telegram_outbox(%s,%s,'blocked',30)",(retry['id'],retry['lease_token']))
        assert c.execute('select telegram_status(%s)',(person,)).fetchone()[0]['notifications_enabled'] is False
        assert c.execute('select resolve_telegram_actor(%s)',(user,)).fetchone()[0]['id']==person
        notify(c,person)
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]
        c.execute('select set_telegram_settings(%s,true)',(person,))
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]
        notify(c,person)
        row=c.execute('select claim_telegram_outbox(100)').fetchone()[0][0]
        c.execute('select set_telegram_settings(%s,false)',(person,))
        assert c.execute("select ack_telegram_outbox(%s,%s,'sent',30)",(row['id'],row['lease_token'])).fetchone()[0]['recorded'] is False
        c.execute('select set_telegram_settings(%s,true)',(person,))
        notify(c,person)
        c.execute('select unlink_telegram(%s)',(person,))
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]


def test_offset_is_durable_monotonic(team_db):
    with team_db.connect() as c:
        assert c.execute('select telegram_worker_offset(100,null)').fetchone()[0]=={'bot_id':100,'offset':0}
        assert c.execute('select telegram_worker_offset(100,123)').fetchone()[0]=={'bot_id':100,'offset':123}
        assert c.execute('select telegram_worker_offset(100,10)').fetchone()[0]=={'bot_id':100,'offset':123}
        assert c.execute('select telegram_worker_offset(200,null)').fetchone()[0]=={'bot_id':200,'offset':0}
        assert c.execute('select telegram_worker_offset(200,3)').fetchone()[0]=={'bot_id':200,'offset':3}
        assert c.execute('select telegram_worker_offset(100,null)').fetchone()[0]=={'bot_id':100,'offset':123}
        with sqlstate('PT422'): c.execute('select telegram_worker_offset(100,-1)')


def test_retries_are_bounded_and_profile_removal_revokes_identity(team_db,person):
    user=link(team_db,person)
    with team_db.connect() as c:
        notify(c,person)
        row=c.execute('select claim_telegram_outbox(100)').fetchone()[0][0]
    with team_db.connect(None) as c:
        c.execute("update telegram_outbox set attempts=8,lease_until=now()-interval '1 second' where id=%s",(row['id'],))
    with team_db.connect() as c:
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]
    with team_db.connect(None) as c:
        assert c.execute('select state from telegram_outbox where id=%s',(row['id'],)).fetchone()[0]=='cancelled'
        c.execute('delete from employee_profiles where id=%s',(person,))
    with team_db.connect() as c:
        with sqlstate('PT403'): c.execute('select resolve_telegram_actor(%s)',(user,))


def test_relink_cannot_reuse_old_delivery_lease(team_db,person):
    user=link(team_db,person)
    with team_db.connect(None) as c: other=add_person(c)
    with team_db.connect() as c:
        notify(c,person)
        old=c.execute('select claim_telegram_outbox(100)').fetchone()[0][0]
        assert c.execute('select telegram_status(%s)',(person,)).fetchone()[0]['link_id']==old['link_id']
        c.execute('select unlink_telegram(%s)',(person,))
        code,_=issue(c,other)
        consume(c,code,user)
        current=c.execute('select telegram_status(%s)',(other,)).fetchone()[0]
        assert current['linked'] and current['link_id']!=old['link_id']
        assert c.execute("select ack_telegram_outbox(%s,%s,'sent',30)",(old['id'],old['lease_token'])).fetchone()[0]['recorded'] is False
        assert c.execute('select claim_telegram_outbox(100)').fetchone()[0]==[]


@pytest.mark.parametrize('role',['anon','authenticated'])
def test_no_public_tables_or_rpcs(team_db,person,role):
    calls=[('select telegram_status(%s)',(person,)),('select issue_telegram_link(%s,%s)',(person,'a'*64)),
           ('select consume_telegram_link(%s,1,1,null)',('a'*64,)),('select resolve_telegram_actor(1)',()),
           ('select unlink_telegram(%s)',(person,)),('select set_telegram_settings(%s,true)',(person,)),
           ('select claim_telegram_outbox(20)',()),('select telegram_worker_offset(100,123)',()),
           ("select ack_telegram_outbox(%s,%s,'sent',30)",(str(uuid4()),str(uuid4())))]
    with team_db.connect(role) as c:
        for statement,args in calls:
            with sqlstate('42501'): c.execute(statement,args)
        for table in ('telegram_links','telegram_link_codes','telegram_outbox','telegram_worker_state'):
            with sqlstate('42501'): c.execute('select * from '+table)
