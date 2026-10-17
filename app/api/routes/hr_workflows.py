from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import Field, model_validator

from app.core.security import get_current_user
from app.schemas.common import UserContext
from app.api.routes.workspace import Payload, hr
from app.services.academy import _client, _execute, _all_rows, _command
from app.services.requests import get_request
from app.services import employee_import
from app.services.workflow_summary import operational_summary

router = APIRouter(prefix='/workspace', tags=['HR workflows'])


@router.get('/fulfillment')
def fulfillment_queue(offset: int = Query(0, ge=0), state: Literal['awaiting_hr','processing','completed'] = 'awaiting_hr', actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _execute(_client().table('request_fulfillment').select('*,hr_requests!inner(employee_id,request_type,start_date,end_date,amount,employee_profiles!hr_requests_employee_id_fkey(full_name))').eq('status',state).order('updated_at').order('request_id').range(offset,offset+19)) or []


@router.get('/fulfillment/{request_id}')
def fulfillment_detail(request_id: UUID, actor: UserContext = Depends(get_current_user)):
    get_request(actor, request_id)
    records = _execute(_client().table('request_fulfillment').select('*').eq('request_id',str(request_id)).limit(1)) or []
    if not records:
        return None
    events = _all_rows(lambda: _client().table('fulfillment_events').select('id,action,detail,created_at').eq('request_id',str(request_id)).order('created_at').order('id'))
    deliveries = _execute(_client().table('integration_outbox').select('destination,status,attempts,delivered_at').eq('aggregate_id',str(request_id))) or []
    from app.services.integrations import configured_destinations
    return {**records[0], 'events': events, 'deliveries': deliveries, 'can_send': all(configured_destinations().values())}


class FulfillInput(Payload):
    action: Literal['start','complete']
    reference: str = Field(default='', max_length=200)
    note: str = Field(default='', max_length=2000)


@router.post('/fulfillment/{request_id}')
def fulfill(request_id: UUID, payload: FulfillInput, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    if payload.action == 'start':
        from app.services.integrations import configuration
        # No events should be stranded when the deployment has no receivers.
        if not all(configuration(d) for d in ('1c','documentolog')):
            raise HTTPException(409, 'Подключите оба приёмника или оформите документ вручную')
    return _command('fulfill_hr_request', {'p_actor_id': actor.id, 'p_request_id':str(request_id), 'p_action':payload.action, 'p_reference':payload.reference, 'p_note':payload.note})


@router.get('/employee-import/template')
def import_template(actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return Response('\ufeff' + ','.join(employee_import.HEADERS) + '\r\n', media_type='text/csv', headers={'Content-Disposition':'attachment; filename="employees.csv"'})


class ImportInput(Payload):
    filename: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=2800000)


@router.post('/employee-import/preview')
def import_preview(payload: ImportInput, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return employee_import.preview(actor,payload.filename,payload.content)


@router.post('/employee-import/{batch_id}/apply')
def import_apply(batch_id: UUID, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return employee_import.apply(actor,batch_id)


class TrackStep(Payload):
    course_id: UUID
    days_to_complete: int = Field(ge=1,le=365)


class TrackInput(Payload):
    id: UUID
    title: str = Field(min_length=3,max_length=160)
    steps: list[TrackStep] = Field(min_length=1,max_length=30)
    auto_role: Literal['worker','manager','hr_admin'] | None = None


@router.get('/tracks')
def tracks(actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _all_rows(lambda: _client().table('learning_tracks').select('*,learning_track_steps(*,courses(title))').eq('active',True).order('created_at').order('id'))


@router.post('/tracks',status_code=201)
def create_track(payload: TrackInput, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _command('create_learning_track', {'p_actor_id':actor.id, **{f'p_{k}':v for k,v in payload.model_dump(mode='json').items()}})


@router.delete('/tracks/{track_id}')
def archive_track(track_id: UUID, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    # Enrolled employees keep their immutable course plan. New hires stop enrolling.
    return _execute(_client().table('learning_tracks').update({'active':False,'auto_role':None}).eq('id',str(track_id)))


class EnrollmentInput(Payload):
    employee_id: UUID


@router.post('/tracks/{track_id}/enroll')
def enroll(track_id: UUID, payload: EnrollmentInput, actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _command('enroll_learning_track',dict(p_actor_id=actor.id,p_track_id=str(track_id),p_employee_id=str(payload.employee_id)))


@router.get('/my-tracks')
def my_tracks(employee_id: UUID | None = None, actor: UserContext = Depends(get_current_user)):
    employee = str(employee_id or actor.id)
    if employee != actor.id and actor.role != 'hr_admin':
        if actor.role != 'manager' or not _execute(_client().table('employee_profiles').select('id').eq('id',employee).eq('manager_id',actor.id).limit(1)):
            raise HTTPException(403, 'Access to this employee is forbidden')
    _execute(_client().rpc('advance_learning_tracks',{'p_employee_id':employee}))
    enrolled = _all_rows(lambda: _client().table('learning_enrollments').select('*,learning_tracks(title,learning_track_steps(position,course_id,days_to_complete,courses(title)))').eq('employee_id',employee).order('enrolled_at').order('id'))
    assigned = _all_rows(lambda: _client().table('course_assignments').select('course_id,status,due_on,progress_percent').eq('employee_id',employee).order('id'))
    by_course = {a['course_id']:a for a in assigned}
    for row in enrolled:
        steps = sorted(row['learning_tracks'].pop('learning_track_steps'),key=lambda s:s['position'])
        for step in steps:
            step['assignment'] = by_course.get(step['course_id'])
        row['steps'] = steps
    return enrolled


@router.get('/summary')
def summary(actor: UserContext = Depends(get_current_user)):
    return operational_summary(actor)


class PolicyInput(Payload):
    enabled: bool
    remind_hours: int = Field(ge=1,le=720)
    escalate_hours: int = Field(ge=2,le=1440)
    course_notice_days: int = Field(ge=0,le=30)

    @model_validator(mode='after')
    def order(self):
        if self.escalate_hours <= self.remind_hours:
            raise ValueError('Эскалация должна быть позже напоминания')
        return self


@router.get('/workflow-policy')
def policy(actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _execute(_client().table('workflow_policy').select('*').eq('id',True))[0]


@router.put('/workflow-policy')
def save_policy(payload: PolicyInput, actor: UserContext = Depends(get_current_user)):
    from datetime import datetime, UTC
    hr(actor)
    return _execute(_client().table('workflow_policy').update({**payload.model_dump(), 'updated_by':actor.id, 'updated_at':datetime.now(UTC).isoformat()}).eq('id',True))[0]


@router.post('/workflow-policy/run')
def run_policy(actor: UserContext = Depends(get_current_user)):
    hr(actor)
    return _command('run_workflow_reminders',{})
