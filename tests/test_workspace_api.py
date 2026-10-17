from uuid import UUID,uuid4
import pytest
from pydantic import ValidationError
from app.api.routes.workspace import CourseData
from app.schemas.common import UserContext
from test_academy import api, WORKER,OTHER,MANAGER,HR,COURSE


def test_ticket_filter_applies_before_paging_and_keeps_employee_scope(api, monkeypatch):
    from test_academy import Query
    patterns = []
    def ilike(query, field, pattern):
        patterns.append(pattern)
        term = pattern[1:-1].replace('\\%', '%').replace('\\_', '_').replace('\\*', '*')
        query.filters.append(lambda row: term.casefold() in row.get(field, '').casefold())
        return query
    monkeypatch.setattr(Query, 'ilike', ilike, raising=False)
    client, db, actor = api
    db.tables['hr_tickets'] = [dict(id=str(uuid4()), employee_id=WORKER, status='resolved', question='old') for _ in range(60)]
    wanted = dict(id=str(uuid4()), employee_id=WORKER, status='open', question='Нужно 100% уточнение')
    db.tables['hr_tickets'] += [wanted, {**wanted, 'id':str(uuid4()), 'employee_id':OTHER}]
    response = client.get('/api/v1/workspace/tickets', params={'limit':12,'status':'open','search':'100%'})
    assert response.status_code == 200
    assert response.json() == [wanted]
    assert patterns == ['%100\\%%']
    assert client.get('/api/v1/workspace/tickets?status=invalid').status_code == 422
    actor['user'] = UserContext(id=HR, auth_user_id=str(uuid4()), role='hr_admin')
    assert len(client.get('/api/v1/workspace/tickets?status=open').json()) == 2

def test_only_hr_can_access_answer_keys_and_editor(api):
    client,db,actor=api
    assert client.get('/api/v1/workspace/courses').status_code==403
    actor['user']=UserContext(id=MANAGER,auth_user_id=str(uuid4()),role='manager')
    assert client.get('/api/v1/workspace/courses').status_code==403
    actor['user']=UserContext(id=HR,auth_user_id=str(uuid4()),role='hr_admin')
    assert 'answer_index' in client.get('/api/v1/workspace/courses').json()[0]['quiz'][0]

def test_kk_course_translation_does_not_leak_answer_keys(api):
    client,db,_=api
    course=db.tables['courses'][0]
    course['translations']={'kk':dict(title='Қауіпсіздік',description='Оқу',material_markdown='Материал',quiz=[dict(id='q1',prompt='Сұрақ',options=['А','Б'],answer_index=1)])}
    result=client.get(f'/api/v1/academy/courses/{COURSE}',headers={'Accept-Language':'kk-KZ'})
    assert result.headers['Content-Language']=='kk'
    assert result.json()['title']=='Қауіпсіздік'
    assert result.json()['quiz']==[dict(id='q1',prompt='Сұрақ',options=['А','Б'])]
    assert 'translations' not in result.json()
    assert client.get(f'/api/v1/academy/courses/{COURSE}').json()['title']=='Test'

def test_ticket_scope_and_explicit_consent(api):
    client,db,actor=api
    id=str(uuid4());foreign=str(uuid4())
    db.tables['hr_tickets']=[dict(id=id,employee_id=WORKER,question='My question'),dict(id=foreign,employee_id=OTHER,question='Private')]
    assert len(client.get('/api/v1/workspace/tickets').json())==1
    assert client.get(f'/api/v1/workspace/tickets/{foreign}').status_code==404
    assert client.post('/api/v1/workspace/tickets',json=dict(id=id,question='Question',context='Context')).status_code==422
    assert client.post('/api/v1/workspace/tickets',json=dict(id=id,question='Question',context='Context',consent=False)).status_code==422
    assert client.post(f'/api/v1/workspace/tickets/{id}/answer',json={'answer':'Answer'}).status_code==403
    actor['user']=UserContext(id=HR,auth_user_id=str(uuid4()),role='hr_admin')
    assert len(client.get('/api/v1/workspace/tickets').json())==2

def test_translated_quiz_cannot_change_scoring():
    q=dict(id='q1',prompt='Question',options=['First','Second'],answer_index=0)
    content=dict(title='Title',description='',material_markdown='Material',quiz=[q])
    data={**content,'duration_minutes':10,'passing_score':80,'category':'Test','audience':'All','translations':{'kk':{**content,'quiz':[{**q,'answer_index':1}]}}}
    with pytest.raises(ValidationError):CourseData.model_validate(data)
