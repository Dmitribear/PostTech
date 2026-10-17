"""End-to-end checks on marked fictional jury accounts only; never sends email."""
import base64
import csv
import io
import json
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parent))
from verify_live_workflow import API, ROOT, require, read_json, save_checkpoint, checkpoint_lock, now


def run():
    api=API('http://127.0.0.1:8000');credentials=read_json(ROOT/'.local/jury-credentials.json')
    require(credentials['project_ref']=='zcsoipcwymhowmvnytxf','Unexpected project')
    profiles={}
    for role in ('employee','manager','hr'):
        account=credentials[role]
        require(account['email']==f"jury.{role}+{credentials['fixture_id']}@posttech.demo",'Not a jury fixture')
        auth=api.call('POST','/auth/login',body={k:account[k] for k in ('email','password')});api.tokens[role]=auth['access_token']
        profile=api.call('GET','/profile',role)
        require(profile['external_source']=='posttech-jury-fixture' and profile['id']==account['profile_id'],'Synthetic marker missing')
        profiles[role]=profile
    checkpoint=ROOT/'.local/hr-workflows-live.json'
    with checkpoint_lock(checkpoint):
        state=read_json(checkpoint) if checkpoint.exists() else dict(fixture_id=credentials['fixture_id'],**{k:str(uuid4()) for k in ('request_key','track','course1','course2','quiz1','quiz2','import_code')})
        require(state['fixture_id']==credentials['fixture_id'],'Checkpoint mismatch');save_checkpoint(checkpoint,state)
        for role in ('employee','manager'):
            for endpoint in ('/fulfillment','/tracks','/workflow-policy'):
                api.call('GET','/workspace'+endpoint,role,expected=403)
        r=api.call('POST','/requests','employee',dict(request_type='advance',amount=1500,comment='Проверка этапов HR — вымышленный сотрудник'),expected=201,key=state['request_key'])
        state['request_id']=r['id'];save_checkpoint(checkpoint,state)
        if r['status']=='pending':api.call('PATCH',f"/requests/{r['id']}/review",'manager',dict(status='approved',reviewer_comment='Тест оформления HR'))
        f=api.call('GET',f"/workspace/fulfillment/{r['id']}",'employee')
        api.call('POST',f"/workspace/fulfillment/{r['id']}",'employee',dict(action='complete',reference='ТЕСТ-123'),expected=403)
        if f['status']!='completed':
            require(f['status']=='awaiting_hr' and not f['deliveries'],'Approval must not auto-deliver')
            api.call('POST',f"/workspace/fulfillment/{r['id']}",'hr',dict(action='complete',reference='ТЕСТ-123'))
        api.call('POST',f"/workspace/fulfillment/{r['id']}",'hr',dict(action='complete',reference='ТЕСТ-123'))
        require(api.call('GET',f"/requests/{r['id']}",'employee')['fulfillment']['status']=='completed','Final stage absent')
        api.call('GET','/workspace/fulfillment?state=completed','hr')
        courses=api.call('GET','/workspace/courses','hr')
        for i in (1,2):
            course=next((c for c in courses if c['id']==state[f'course{i}']),None)
            if not course:
                content=dict(title=f'Тест адаптации · шаг {i}',description='Проверка последовательного обучения на вымышленном сотруднике.',duration_minutes=2,passing_score=80,category='Проверка',audience='Тестовый сотрудник',material_markdown='Изучите материал и отметьте правильный ответ.',translations={},lessons=[],quiz=[dict(id='q1',prompt='Как завершить обучение?',options=['Пройти тест','Закрыть страницу'],answer_index=0)])
                course=api.call('POST','/workspace/courses','hr',dict(id=state[f'course{i}'],action='create',data=content))
            if course['publication_state']=='draft':api.call('POST','/workspace/courses','hr',dict(id=course['id'],action='publish',revision=course['revision']))
        tracks=api.call('GET','/workspace/tracks','hr')
        if not any(t['id']==state['track'] for t in tracks) and not state.get('archived'):
            api.call('POST','/workspace/tracks','hr',dict(id=state['track'],title='Проверка адаптации · два шага',steps=[dict(course_id=state['course1'],days_to_complete=2),dict(course_id=state['course2'],days_to_complete=3)]),expected=201)
        if not state.get('archived'):
            api.call('POST',f"/workspace/tracks/{state['track']}/enroll",'hr',dict(employee_id=profiles['employee']['id']))
        plan=next(t for t in api.call('GET','/workspace/my-tracks','employee') if t['track_id']==state['track'])
        if plan['steps'][0]['assignment']['status']!='completed':
            require(plan['steps'][1]['assignment'] is None,'Future step prematurely assigned')
            api.call('GET',f"/academy/courses/{state['course2']}",'employee',expected=403)
        for i in (1,2):
            course=api.call('GET',f"/academy/courses/{state[f'course{i}']}",'employee')
            if course['assignment']['status']!='completed':
                api.call('PATCH',f"/academy/courses/{course['id']}/progress",'employee',dict(progress_percent=90))
                result=api.call('POST',f"/academy/courses/{course['id']}/complete",'employee',dict(answers={'q1':0}),key=state[f'quiz{i}'])
                require(result['status']=='completed','Quiz not completed')
        plan=next(t for t in api.call('GET','/workspace/my-tracks','employee') if t['track_id']==state['track'])
        require(plan['completed_at'] and all(s['assignment']['status']=='completed' for s in plan['steps']),'Plan incomplete')
        if not state.get('import_id'):
            from openpyxl import Workbook
            headers=['employee_code','full_name','email','company','job_title','department','hired_at','role','manager_email']
            values=['WF-'+state['import_code'],'Вымышленный сотрудник импорта','workflow-'+state['import_code']+'@posttech.demo','PostTech','Тест','Проверка','2026-10-17','worker',profiles['manager']['email']]
            csv_io=io.StringIO();csv.writer(csv_io).writerows([headers,values])
            preview=api.call('POST','/workspace/employee-import/preview','hr',dict(filename='test.csv',content=base64.b64encode(csv_io.getvalue().encode('utf-8')).decode()))
            require(not preview['errors'] and preview['rows'][0]['action']=='invite','CSV preview failed')
            book=Workbook();book.active.append(headers);book.active.append(values);excel=io.BytesIO();book.save(excel)
            preview=api.call('POST','/workspace/employee-import/preview','hr',dict(filename='test.xlsx',content=base64.b64encode(excel.getvalue()).decode()))
            require(not preview['errors'],'Excel preview failed');state['import_id']=preview['id'];save_checkpoint(checkpoint,state)
        result=api.call('POST',f"/workspace/employee-import/{state['import_id']}/apply",'hr')
        # Raw invitation codes are neither printed nor persisted by this verification.
        invitation=result['invitations'][0];state['invitation_id']=invitation['id'];save_checkpoint(checkpoint,state)
        repeat=api.call('POST',f"/workspace/employee-import/{state['import_id']}/apply",'hr');require(repeat['already_applied'],'Import not idempotent')
        api.call('POST',f"/auth/invitations/{invitation['id']}/revoke",'hr')
        for role in ('employee','manager','hr'):
            summary=api.call('POST','/ai/ask',role,dict(question='Что требует внимания?'))
            require(summary['mode']=='summary' and summary['report']['sections'],'Missing scoped summary')
        policy=api.call('GET','/workspace/workflow-policy','hr');require(policy['last_run_at'],'Worker heartbeat missing')
        api.call('POST','/workspace/workflow-policy/run','hr')
        repeat=api.call('POST','/workspace/workflow-policy/run','hr');require(repeat['sent']==0,'Duplicate reminders')
        if not state.get('archived'):
            api.call('DELETE',f"/workspace/tracks/{state['track']}",'hr');state['archived']=True;save_checkpoint(checkpoint,state)
        for course in api.call('GET','/workspace/courses','hr'):
            if course['id'] in (state['course1'],state['course2']) and course['active']:
                api.call('POST','/workspace/courses','hr',dict(id=course['id'],action='archive',revision=course['revision']))
        report=dict(verified_at=now(),scope='Docker + real Supabase, marked fictional accounts only',api_calls=api.calls,fulfillment='manager approval → HR document; retry safe',employee_import='CSV + XLSX preview → invitation → duplicate protection → revoked test invitation',learning='sequential unlock, both tests passed, plan completed; test courses archived',jana='scoped report for worker, manager, HR',reminders='worker heartbeat confirmed; repeated cycle sent zero duplicates',emails_sent=0,external_document_systems_connected=False)
        (ROOT/'docs/performance/hr-workflows-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({'verified':True,'api_calls':api.calls,'scenarios':5}))


if __name__=='__main__':run()
