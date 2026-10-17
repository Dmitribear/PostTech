"""Operational extensions; employee data is scoped before service-key reads."""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, HttpUrl

from app.api.routes.workspace import Payload, hr
from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.services.academy import _client, _execute, _command
from app.services.requests import get_request
from app.services.integrations import configured_destinations

router = APIRouter(prefix="/workspace", tags=["Operations"])


@router.get('/leave-balance')
def leave_balance(employee_id: UUID | None = None, request_id: UUID | None = None,
                  actor: UserContext = Depends(get_current_user)):
    employee = str(employee_id or actor.id)
    request = None
    if request_id:
        request = get_request(actor, request_id)
        employee = str(request['employee_id'])
    q = _client().table('employee_profiles').select('id,manager_id,vacation_days_remaining,updated_at').eq('id', employee)
    rows = _execute(q.limit(1)) or []
    if not rows or (employee != actor.id and actor.role != 'hr_admin' and not (request and request.get('can_review'))
                    and not (actor.role == 'manager' and str(rows[0]['manager_id']) == actor.id)):
        raise HTTPException(404, 'Employee not found')
    balance = _command('read_leave_balance', {'p_employee_id':employee})
    balance['request_days'] = next((x['days'] for x in balance['holds'] if request and str(x['request_id']) == str(request['id'])), 0)
    return balance


class BalanceInput(Payload):
    id: UUID
    employee_id: UUID
    days: float = Field(ge=0, le=999, multiple_of=0.5)
    requests: list[UUID] = Field(max_length=200)
    note: str = Field(min_length=3, max_length=1000)


@router.post('/leave-balance/reconcile')
def reconcile(payload: BalanceInput, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _command('reconcile_leave_balance', {'p_actor_id': actor.id, **{f'p_{k}': v for k, v in payload.model_dump(mode='json').items()}})


class KnowledgeContent(Payload):
    title: str = Field(min_length=3, max_length=200)
    content: str = Field(min_length=3, max_length=60000)
    source_title: str = Field(min_length=3, max_length=300)
    source_url: HttpUrl | None = None
    keywords: list[str] = Field(default_factory=list, max_length=50)


class KnowledgeEdit(Payload):
    id: UUID
    revision: int = Field(default=0, ge=0)
    action: Literal['create', 'save', 'approve', 'archive']
    data: KnowledgeContent | None = None
    due: date | None = None


@router.get('/knowledge')
def knowledge(actor: UserContext = Depends(get_current_user), offset: int = Query(0, ge=0),
              limit: int = Query(20, ge=1, le=100)):
    hr(actor)
    return _execute(_client().table('knowledge_articles').select('*').order('created_at', desc=True).order('id').range(offset, offset+limit-1)) or []


@router.get('/knowledge/{article_id}/history')
def knowledge_history(article_id: UUID, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _execute(_client().table('knowledge_events').select('id,actor_id,action,revision,created_at')
                    .eq('article_id', str(article_id)).order('created_at', desc=True).limit(100)) or []


@router.post('/knowledge')
def edit_knowledge(payload: KnowledgeEdit, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    if payload.action in ('create', 'save') and not payload.data:
        raise HTTPException(422, 'Source content required')
    return _command('edit_knowledge_article', dict(p_actor_id=actor.id, p_id=str(payload.id), p_action=payload.action,
        p_revision=payload.revision, p_data=payload.data.model_dump(mode='json') if payload.data else {},
        p_due=payload.due.isoformat() if payload.due else None))


@router.get('/integrations')
def integrations(actor: UserContext = Depends(get_current_user), offset: int = Query(0, ge=0),
                 status: Literal['queued','sending','retry','delivered','dead'] | None = None):
    hr(actor)
    q = _client().table('integration_outbox').select('id,destination,event_type,aggregate_id,status,attempts,next_attempt_at,last_error,delivered_at,created_at')
    if status:
        q = q.eq('status', status)
    return {'connected': configured_destinations(), 'events': _execute(q.order('created_at',desc=True).order('id').range(offset,offset+19)) or []}


@router.get('/integrations/{event_id}/attempts')
def attempts(event_id: UUID, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _execute(_client().table('integration_attempts').select('attempt,outcome,detail,created_at')
        .eq('event_id',str(event_id)).order('created_at',desc=True).limit(100)) or []


@router.post('/integrations/{event_id}/retry')
def retry(event_id: UUID, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    _command('retry_integration_event', dict(p_actor_id=actor.id,p_id=str(event_id)))
    return {'queued': True}


@router.post('/courses/{course_id}/lessons/{lesson_id}/complete')
def complete_lesson(course_id: UUID, lesson_id: str, actor: UserContext = Depends(get_current_user)):
    return _command('complete_academy_lesson', dict(p_actor_id=actor.id,p_course_id=str(course_id),p_lesson_id=lesson_id))
