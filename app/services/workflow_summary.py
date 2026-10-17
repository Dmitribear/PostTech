"""Operational facts use authenticated scope and never go to an LLM."""
from datetime import datetime, date
from zoneinfo import ZoneInfo
from uuid import UUID

from app.services.academy import _client, _all_rows
from app.services.requests import list_requests


def operational_summary(actor):
    today = datetime.now(ZoneInfo('Asia/Almaty')).date()
    def people_query():
        q = _client().table('employee_profiles').select('id,full_name').order('id')
        if actor.role == 'worker':
            q = q.eq('id', actor.id)
        elif actor.role in ('manager', 'director'):
            q = q.or_(f'id.eq.{actor.id},manager_id.eq.{actor.id}')
        return q
    people = {p['id']: p['full_name'] for p in _all_rows(people_query)}
    requests, offset = [], 0
    while True:
        rows = list_requests(actor, limit=100, offset=offset)
        requests.extend(rows)
        if len(rows) < 100:
            break
        offset += 100
    pending = [r for r in requests if r['status'] in ('pending', 'pending_hr') and (r['employee_id'] == actor.id if actor.role == 'worker' else r['can_review'])]
    pending.sort(key=lambda r: (r['created_at'], r['id']))
    def request_label(r):
        kind = ('Отпуск · ' + r['start_date'] + ' — ' + r['end_date']) if r['request_type'] == 'leave' else 'Аванс'
        name = people.get(r['employee_id'], 'Заявка ' + r['id'][:8])
        return kind if actor.role == 'worker' else name + ' · ' + kind
    sections = [{
        'title': 'Мои заявки на согласовании' if actor.role == 'worker' else 'Ждут вашего решения',
        'count': len(pending), 'href': '/requests' if actor.role == 'worker' else '/requests?scope=review',
        'items': [{'label': request_label(r), 'href': '/requests/' + r['id']} for r in pending[:8]],
    }]
    assignments = []
    ids = list(people)
    for index in range(0, len(ids), 100):
        chunk = ids[index:index+100]
        assignments.extend(_all_rows(lambda: _client().table('course_assignments').select('id,employee_id,course_id,due_on').in_('employee_id', chunk).neq('status', 'completed').lt('due_on', today.isoformat()).order('due_on').order('id')))
    assignments.sort(key=lambda a: (a['due_on'], a['id']))
    sections.append({'title': 'Просрочено обучение', 'count': len(assignments), 'href': '/academy' if actor.role == 'worker' else '/academy?tab=team',
        'items': [{'label': people[a['employee_id']] + ' · до ' + a['due_on'], 'href': '/academy?course=' + a['course_id'] if a['employee_id'] == actor.id else '/team?tab=learning&employee=' + a['employee_id']} for a in assignments[:8]]})
    if actor.role != 'worker':
        leaves = [r for r in requests if r['request_type'] == 'leave' and r['status'] in ('pending','pending_hr','approved') and r['employee_id'] in people and date.fromisoformat(r['end_date']) >= today]
        overlaps = []
        # Sweep by start date; count pairs without inventing a staffing limit.
        active = []
        count = 0
        for r in sorted(leaves, key=lambda x: (x['start_date'], x['id'])):
            active = [p for p in active if p['end_date'] >= r['start_date']]
            for p in active:
                if p['employee_id'] != r['employee_id']:
                    count += 1
                    if len(overlaps) < 8:
                        overlaps.append({'label': people[p['employee_id']] + ' / ' + people[r['employee_id']] + ' · ' + max(p['start_date'], r['start_date']) + ' — ' + min(p['end_date'], r['end_date']), 'href': '/requests/' + r['id']})
            active.append(r)
        sections.append({'title': 'Пересечения отпусков', 'count': count, 'href': '/calendar', 'items': overlaps})
    if actor.role == 'hr_admin':
        waiting = _all_rows(lambda: _client().table('request_fulfillment').select('request_id,status,updated_at').neq('status','completed').order('updated_at').order('request_id'))
        by_id = {r['id']:r for r in requests}
        sections.append({'title': 'Ожидают оформления HR', 'count': len(waiting), 'href': '/hr-workflow', 'items': [{'label': request_label(by_id[r['request_id']]) if r['request_id'] in by_id else 'Заявка ' + r['request_id'][:8], 'href': '/requests/' + r['request_id']} for r in waiting[:8]]})
    return {'as_of': datetime.now(ZoneInfo('Asia/Almaty')).isoformat(), 'sections': sections}
