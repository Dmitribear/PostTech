"""Remove only records created by verify_portal_refresh.cjs."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.infrastructure.config import get_settings
from app.infrastructure.database.client import get_supabase_client


def run():
    report_path = ROOT / '.local/portal-refresh-report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    accounts = json.loads((ROOT / '.local/scenario-credentials.json').read_text())
    assert accounts['project_ref'] == 'zcsoipcwymhowmvnytxf'
    assert str(get_settings().supabase_url).rstrip('/') == 'https://zcsoipcwymhowmvnytxf.supabase.co'
    marker = report['marker']
    assert marker.startswith('[SYNTHETIC PORTAL REFRESH] ') and len(marker) == 59
    db = get_supabase_client()
    owners = {accounts[role]['profile_id']: accounts[role]['email'] for role in ('employee', 'manager', 'director', 'hr')}
    rows = db.table('hr_requests').select('id,employee_id,comment').eq('comment', marker).execute().data
    for row in rows:
        assert row['employee_id'] in owners and row['comment'] == marker
        profile = db.table('employee_profiles').select('email,external_source').eq('id', row['employee_id']).single().execute().data
        assert profile['external_source'] == 'posttech-scenario-check'
        assert profile['email'] == owners[row['employee_id']]
        db.table('integration_outbox').delete().eq('aggregate_id', row['id']).execute()
        db.table('fulfillment_events').delete().eq('request_id', row['id']).execute()
        db.table('hr_requests').delete().eq('id', row['id']).eq('employee_id', row['employee_id']).eq('comment', marker).execute()
    assert not db.table('hr_requests').select('id').eq('comment', marker).execute().data
    print('Removed only this run\'s synthetic requests and reservations.')


if __name__ == '__main__':
    try:
        run()
    except Exception as exc:
        print('Cleanup failed: ' + type(exc).__name__)
        raise SystemExit(1)
