const { chromium, request, expect } = require('../frontend/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');
const { randomUUID } = require('crypto');
const { execFileSync } = require('child_process');

const root = path.resolve(__dirname, '..');
const accounts = JSON.parse(fs.readFileSync(path.join(root, '.local/scenario-credentials.json'), 'utf8'));
const baseURL = 'http://127.0.0.1:8000';
const reportPath = path.join(root, '.local/portal-refresh-report.json');
const marker = '[SYNTHETIC PORTAL REFRESH] ' + randomUUID().replaceAll('-', '');
const report = { at: new Date().toISOString(), marker, results: [], requests: [], baseline: {}, status: 'running' };
const save = () => fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
const check = (value, message) => { if (!value) throw Error(message); };
const clients = {}, sessions = {};
async function call(role, method, route, data) {
  const response = await clients[role][method]('/api/v1' + route, { data });
  check(response.ok(), `${role} ${method} ${route}: HTTP ${response.status()}`);
  return response.json();
}
const requestLink = (page, id) => page.locator(`a[href="/requests/${id}"]`).first();
const note = (page, id) => page.locator('article').filter({ has: page.locator(`a[href="/requests/${id}"]`) }).first();
const statusText = { approved: /Согласован|Одобрен|Ожидает HR/i, rejected: /Отклонен/i, cancelled: /Отменен|Отменён|Отозван/i };
async function assertBalance(page, days) {
  await expect(page.locator('.desk-leave-copy')).toContainText(`${days} дн. доступно`, { timeout: 20000 });
}
async function assertBadge(page, role) {
  const unread = await call(role, 'get', '/notifications?unread_only=true&limit=100');
  await expect(page.locator('.notification-button')).toHaveAttribute('aria-label', `Уведомления: ${unread.length} непрочитанных`, { timeout: 20000 });
}

(async () => {
  check(accounts.project_ref === 'zcsoipcwymhowmvnytxf', 'Unexpected fixture project');
  const browser = await chromium.launch({ headless: true, executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || 'C:/Users/juven/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe' });
  let originalDirectorRole;
  save();
  try {
    for (const role of ['employee', 'manager', 'director', 'hr', 'backup_hr']) {
      const account = accounts[role];
      check(account.email === `scenario.${role}+${accounts.fixture_id}@posttech.demo`, 'Not a synthetic account');
      const http = await request.newContext({ baseURL });
      const response = await http.post('/api/v1/auth/login', { data: { email: account.email, password: account.password } });
      check(response.ok(), 'Fixture login failed: ' + role);
      sessions[role] = await response.json();
      await http.dispose();
      clients[role] = await request.newContext({ baseURL, extraHTTPHeaders: { Authorization: `Bearer ${sessions[role].access_token}` } });
      const profile = await call(role, 'get', '/profile');
      check(profile.id === account.profile_id && profile.external_source === 'posttech-scenario-check', 'Fixture identity mismatch');
      if (role === 'director') originalDirectorRole = profile.role;
      if (role !== 'backup_hr') report.baseline[role] = await call(role, 'get', '/workspace/leave-balance');
    }
    save();
    if (originalDirectorRole !== 'director') await call('hr', 'patch', `/admin/employees/${accounts.director.profile_id}/role`, { role: 'director' });
    for (const role of ['employee', 'manager', 'director', 'hr']) {
      const routing = await call(role, 'get', '/requests/routing');
      const reviewer = Object.keys(clients).find(key => key !== role && routing.approvers.some(p => p.id === accounts[key].profile_id));
      check(reviewer, 'Missing synthetic reviewer for ' + role);
      for (const width of [1440, 390]) {
        const contexts = [];
        const pages = [];
        const errors = [];
        async function open(actor, route) {
          const context = await browser.newContext({ viewport: { width, height: 900 }, isMobile: width < 500, hasTouch: width < 500, locale: 'ru-RU' });
          contexts.push(context);
          await context.addInitScript(s => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({ ...s, expires_at: Date.now() + s.expires_in * 1000 })), sessions[actor]);
          const page = await context.newPage();
          page.on('pageerror', e => errors.push(e.name));
          await page.goto(baseURL + route);
          pages.push(page);
          return page;
        }
        try {
          const home = await open(role, '/');
          const notifications = await open(role, '/notifications');
          const ownList = await open(role, '/requests?scope=mine');
          const queue = await open(reviewer, '/requests?scope=review&status=pending');
          const reviewNotes = await open(reviewer, '/notifications');
          await expect(notifications.getByRole('heading', { name: 'Уведомления', exact: true })).toBeVisible();
          await expect(queue.locator('.req-list-card')).toBeVisible();
          for (const decision of ['cancelled', 'rejected', 'approved']) {
            const baseline = await call(role, 'get', '/workspace/leave-balance');
            check(baseline.available_days >= 1, 'Not enough synthetic leave');
            await assertBalance(home, baseline.available_days);
            const rows = await call(role, 'get', '/requests?scope=mine&limit=100');
            let date = new Date(Date.now() + 600 * 86400000).toISOString().slice(0, 10);
            while (rows.some(r => r.request_type === 'leave' && ['pending', 'approved'].includes(r.status) && r.start_date <= date && date <= r.end_date)) date = new Date(new Date(date).getTime() + 86400000).toISOString().slice(0, 10);
            const created = await call(role, 'post', '/requests', { request_type: 'leave', start_date: date, end_date: date, comment: marker });
            report.requests.push({ id: created.id, role, width, decision }); save();
            const start = Date.now();
            await expect(requestLink(queue, created.id)).toBeVisible({ timeout: 20000 });
            await expect(note(reviewNotes, created.id)).toBeVisible({ timeout: 20000 });
            await expect(requestLink(home, created.id)).toBeVisible({ timeout: 20000 });
            await expect(requestLink(ownList, created.id)).toBeVisible({ timeout: 20000 });
            await assertBalance(home, baseline.available_days - 1);
            await assertBadge(queue, reviewer);
            const creationMs = Date.now() - start;
            const detail = await open(role, `/requests/${created.id}`);
            await expect(detail.getByRole('region', { name: 'Состояние заявки' })).toContainText('Ждёт решения');
            const navigationCounts = new Map(pages.map(p => [p, 0]));
            const listeners = pages.map(p => {
              const listener = frame => { if (frame === p.mainFrame()) navigationCounts.set(p, navigationCounts.get(p) + 1); };
              p.on('framenavigated', listener); return [p, listener];
            });
            if (decision === 'cancelled') await call(role, 'post', `/requests/${created.id}/cancel`);
            else await call(reviewer, 'patch', `/requests/${created.id}/review`, { status: decision, reviewer_comment: marker });
            const decisionStart = Date.now();
            await expect(requestLink(home, created.id)).toContainText(statusText[decision], { timeout: 20000 });
            await expect(detail.getByRole('region', { name: 'Состояние заявки' })).toContainText(statusText[decision], { timeout: 20000 });
            await expect(requestLink(queue, created.id)).toHaveCount(0, { timeout: 20000 });
            await expect(note(notifications, created.id)).toBeVisible({ timeout: 20000 });
            await assertBalance(home, baseline.available_days - (decision === 'approved' ? 1 : 0));
            await assertBadge(home, role);
            const decisionMs = Date.now() - decisionStart;
            const notes = await call(role, 'get', '/notifications?limit=100');
            const currentNote = notes.find(n => n.request_id === created.id && !n.read_at);
            check(currentNote, 'Missing unread decision notification');
            await call(role, 'post', `/notifications/${currentNote.id}/read`);
            await expect(note(notifications, created.id)).not.toHaveClass(/unread/, { timeout: 20000 });
            await assertBadge(home, role);
            for (const p of pages) {
              if (p.isClosed()) continue;
              check(await p.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Horizontal overflow: ${role}/${width}`);
              check(navigationCounts.get(p) === 0, 'Page reloaded during update');
            }
            check(!errors.length, 'Browser JavaScript error');
            for (const [p, listener] of listeners) p.off('framenavigated', listener);
            if (decision === 'rejected') await home.screenshot({ path: path.join(root, `.local/refresh-${role}-${width}.png`) });
            report.results.push({ role, reviewer, width, decision, creationMs, decisionMs, noReload: true, balance: true, notifications: true, badge: true, queue: true, details: true, noOverflow: true });
            save(); console.log(JSON.stringify(report.results.at(-1)));
            await detail.context().close(); pages.splice(pages.indexOf(detail), 1);
          }
        } finally { for (const context of contexts) await context.close(); }
      }
    }
    report.status = 'passed';
  } catch (error) {
    report.status = 'failed';
    report.error = error.message.replaceAll(/Bearer\s+\S+/g, '[redacted]');
    throw error;
  } finally {
    save();
    try {
      execFileSync(path.join(root, '.venv/Scripts/python.exe'), ['-X', 'utf8', 'scripts/cleanup_refresh_check.py'], { cwd: root, stdio: 'pipe' });
      if (originalDirectorRole && originalDirectorRole !== 'director') await call('hr', 'patch', `/admin/employees/${accounts.director.profile_id}/role`, { role: originalDirectorRole });
      for (const [role, baseline] of Object.entries(report.baseline)) {
        const after = await call(role, 'get', '/workspace/leave-balance');
        check(after.available_days === baseline.available_days && after.official_days === baseline.official_days, 'Cleanup balance mismatch: ' + role);
      }
      report.cleanup = 'All run requests removed; balances and director role restored';
    } catch (error) {
      report.status = 'failed';
      report.cleanup = 'Incomplete; inspect this run marker before retrying';
      throw error;
    } finally {
      save();
      for (const client of Object.values(clients)) await client.dispose();
      await browser.close();
    }
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
