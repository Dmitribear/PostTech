from types import SimpleNamespace
import json

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.schemas.auth import RegistrationRequest
from app.services import invitation_email as mail, invitations

INVITE = {'id': 'invite-1', 'email': 'employee@example.test', 'role': 'manager',
          'department': '<script>unsafe</script>', 'expires_at': '2026-12-01T12:00:00+00:00'}


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setattr(mail, 'get_settings', lambda: SimpleNamespace(
        resend_api_key=SecretStr('test-secret'), invitation_email_from='PostTech <onboarding@resend.dev>',
        portal_public_url=None))


def test_email_contains_hr_role_and_code_without_password(monkeypatch):
    def post(url, **kwargs):
        payload = kwargs['json']
        assert payload['to'] == [INVITE['email']]
        assert 'Руководитель' in payload['text'] and 'JP-test-code' in payload['text']
        assert '<script>' not in payload['html']
        assert '&lt;script&gt;' in payload['html']
        assert kwargs['headers']['Idempotency-Key'] == 'invitation/invite-1/hash'
        assert 'test-secret' not in str(payload)
        return httpx.Response(200, json={'id': 'message-id'})
    monkeypatch.setattr(mail.httpx, 'post', post)
    assert mail.send(INVITE, 'JP-test-code', 'hash') == 'accepted'


@pytest.mark.parametrize('role,label', [('worker','Сотрудник'), ('manager','Руководитель'),
                                         ('director','Директор'), ('hr_admin','HR-администратор')])
def test_all_current_roles_render_without_changing_database_authority(monkeypatch,role,label):
    def post(url, **kwargs):
        assert kwargs['json']['to'] == [INVITE['email']]
        assert f'Ваша роль: {label}' in kwargs['json']['text']
        return httpx.Response(200,json={'id':'message-id'})
    monkeypatch.setattr(mail.httpx,'post',post)
    assert mail.send({**INVITE,'role':role},'JP-test-code','hash') == 'accepted'


@pytest.mark.parametrize('payload',[None,[],['message'],42,True,'message',{},
                                      {'id':None},{'id':[]},{'id':42},{'id':True},{'id':''},{'id':' '}])
def test_malformed_success_body_is_unknown_not_500_or_false_acceptance(monkeypatch,payload):
    monkeypatch.setattr(mail.httpx,'post',lambda *a,**k:httpx.Response(200,content=json.dumps(payload)))
    assert mail.send(INVITE,'JP-test','hash') == 'unknown'


def test_director_issue_preserves_created_code_when_provider_reply_is_malformed(monkeypatch):
    from app.schemas.auth import IssueInvitationRequest
    from datetime import date
    invitation = {**INVITE, 'role':'director'}
    calls = []
    def rpc(name, params):
        calls.append((name,params))
        return {'recorded':True} if name=='finish_invitation_email' else invitation
    monkeypatch.setattr(invitations,'_rpc',rpc)
    monkeypatch.setattr(mail.httpx,'post',lambda *a,**k:httpx.Response(200,content='null'))
    result = invitations.issue(SimpleNamespace(id='hr',role='hr_admin'),IssueInvitationRequest(
        email=INVITE['email'],employee_code='123',company='PostTech',job_title='Director',
        department='Operations',hired_at=date(2026,10,17),role='director'))
    assert result['email_status']=='unknown' and result['invitation_code'].startswith('JP-')
    assert [name for name,_ in calls]==['issue_registration_invitation','begin_invitation_email','finish_invitation_email']
    assert calls[0][1]['p_token_hash']==invitations.code_hash(result['invitation_code'])
    assert calls[1][1]['p_token_hash']==calls[0][1]['p_token_hash']
    assert calls[2][1]['p_status']=='unknown'


@pytest.mark.parametrize('status,expected', [(403,'failed'),(429,'failed'),(500,'unknown'),(200,'unknown')])
def test_provider_rejection_is_not_success(monkeypatch,status,expected):
    monkeypatch.setattr(mail.httpx,'post',lambda *a,**k:httpx.Response(status,json={}))
    assert mail.send(INVITE,'JP-test','hash') == expected


def test_timeout_is_unknown_not_false_success(monkeypatch):
    def timeout(*a,**kw): raise httpx.ReadTimeout('secret in provider error')
    monkeypatch.setattr(mail.httpx,'post',timeout)
    assert mail.send(INVITE,'JP-test','hash') == 'unknown'


@pytest.mark.parametrize('role',['worker','manager','director'])
def test_worker_cannot_send_or_rotate(monkeypatch,role):
    monkeypatch.setattr(invitations,'_rpc',lambda *a:pytest.fail('Unauthorized RPC'))
    with pytest.raises(HTTPException) as error:
        invitations.resend(SimpleNamespace(id='actor',role=role),'invite-1')
    assert error.value.status_code == 403


def test_unconfigured_sender_never_rotates_code(monkeypatch):
    monkeypatch.setattr(mail,'configured',lambda:False)
    monkeypatch.setattr(invitations,'_rpc',lambda *a:pytest.fail('Code must not rotate'))
    with pytest.raises(HTTPException) as error:
        invitations.resend(SimpleNamespace(id='hr',role='hr_admin'),'invite-1')
    assert error.value.status_code == 503


def test_retry_uses_database_recipient_and_role(monkeypatch):
    calls=[]
    def rpc(name,params):
        calls.append((name,params))
        return INVITE if name=='begin_invitation_email' else {'recorded':True}
    monkeypatch.setattr(invitations,'_rpc',rpc)
    monkeypatch.setattr(mail,'send',lambda invite,code,digest:'accepted' if invite is INVITE else pytest.fail())
    result=invitations.resend(SimpleNamespace(id='hr',role='hr_admin'),'invite-1')
    assert result['role']=='manager' and result['email']==INVITE['email']
    assert calls[0][1]['p_token_hash']==invitations.code_hash(result['invitation_code'])
    assert calls[1][1]['p_status']=='accepted'


def test_registration_cannot_submit_role():
    with pytest.raises(ValidationError):
        RegistrationRequest(invitation_code='JP-test-code',first_name='Test',last_name='User',
                            password='Test-password9',role='hr_admin')


def test_empty_compose_public_url_is_valid():
    assert Settings(_env_file=None,portal_public_url='').portal_public_url is None


def test_email_settings_preserve_local_reader_defaults_and_explicit_docker_opt_in(monkeypatch):
    monkeypatch.delenv('JANA_READER_URL',raising=False)
    monkeypatch.delenv('JANA_READER_ALLOW_DOCKER_HOST',raising=False)
    native=Settings(_env_file=None)
    assert native.jana_reader_url=='http://127.0.0.1:8081'
    assert native.jana_reader_allow_docker_host is False
    docker=Settings(_env_file=None,jana_reader_url='http://jana-reader:8081',jana_reader_allow_docker_host=True,
                    resend_api_key='test-secret',portal_public_url='http://localhost:8080')
    assert docker.jana_reader_allow_docker_host and docker.resend_api_key.get_secret_value()=='test-secret'
