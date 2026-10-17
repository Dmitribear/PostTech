import { test, expect, type Page, type Route } from '@playwright/test';

const sourceId = '91000000-0000-4000-8000-000000000001';
const employeeId = '91000000-0000-4000-8000-000000000002';
const quote = 'Окончательное решение по отпуску принимает HR.';
const source = { id: sourceId, title: 'Согласование отпуска', url: null, excerpt: quote, version: 'modal-snapshot' };
const answer = { answer: quote, grounded: true, escalation_suggested: false, mode: 'excerpts', sources: [source] };
const reply = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
async function portal(page: Page, ask: (route: Route) => Promise<void> = route => reply(route, answer)) {
  const calls: { path: string; body: any; method: string }[] = [];
  await page.addInitScript(() => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({ user_id: 'test', email: 'test@example.test', access_token: 'test', refresh_token: 'test', token_type: 'bearer', expires_in: 3600, expires_at: Date.now()+3600000 })));
  await page.route('**/api/v1/**', async route => {
    const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api/v1','');
    calls.push({path: path+url.search,body:req.postData()?req.postDataJSON():null,method:req.method()});
    if(path==='/profile')return reply(route,{id:employeeId,employee_code:'TEST',full_name:'Тестовый сотрудник',email:'test@example.test',company:'PostTech',job_title:'Оператор',department:'Склад',manager_id:null,hired_at:'2025-01-01',vacation_days_remaining:24,role:'worker',external_source:'test',created_at:'2026-01-01',updated_at:'2026-01-01'});
    if(path==='/ai/ask')return ask(route);
    if(path===`/ai/sources/${sourceId}`)return reply(route,{id:sourceId,title:source.title,source_title:'Документ HR',source_url:null,content:quote,version:source.version});
    if(path==='/workspace/summary')return reply(route,{as_of:'2026-10-17T10:00:00Z',sections:[{title:'Мои заявки на согласовании',count:1,href:'/requests',items:[{label:'Заявка на отпуск',href:'/requests'}]}]});
    if(path==='/workspace/tickets'&&req.method()==='POST')return reply(route,{id:'ticket-test',employee_id:employeeId,...req.postDataJSON(),status:'open',answer:null,created_at:'2026-10-17'});
    return reply(route,[]);
  });
  return calls;
}
const launcher = (page: Page) => page.getByRole('button',{name:'Открыть AI Jana',exact:true});
const chat = (page: Page) => page.getByRole('dialog',{name:'Чат с AI Jana',exact:true});
async function open(page: Page){await launcher(page).click();await expect(chat(page)).toBeVisible();await expect(chat(page).getByRole('textbox',{name:'Ваш вопрос Jana'})).toBeFocused();}
async function toRequests(page: Page){const nav=page.getByRole('navigation',{name:(page.viewportSize()?.width??1440)<=900?'Быстрая навигация':'Главная навигация'});await nav.getByRole('link',{name:'Заявки',exact:true}).click();await expect(page).toHaveURL(/\/requests$/);}

test('top-right Jana is absent on login, modal traps focus and keeps a draft across pages',async({page},info)=>{
  if(info.project.name==='mobile')await page.setViewportSize({width:320,height:780});
  await page.goto('/login');await expect(launcher(page)).toHaveCount(0);
  await portal(page);await page.goto('/');
  const box=await launcher(page).boundingBox();expect(box!.y).toBeLessThan(80);expect(box!.x+box!.width/2).toBeGreaterThan(page.viewportSize()!.width/2);
  await open(page);await expect(chat(page)).toHaveAttribute('aria-modal','true');
  await chat(page).getByRole('textbox',{name:'Ваш вопрос Jana'}).fill('Мой незаконченный вопрос');
  for(let i=0;i<10;i++){await page.keyboard.press('Tab');expect(await chat(page).evaluate(node=>node.contains(document.activeElement))).toBe(true);}
  await page.keyboard.press('Escape');await expect(chat(page)).toBeHidden();await expect(launcher(page)).toBeFocused();
  let loadPage!:()=>void;const delayedPage=new Promise<void>(resolve=>{loadPage=resolve;});
  await page.route('**/src/pages/Requests.tsx*',async route=>{await delayedPage;await route.continue();});
  await toRequests(page);await open(page);loadPage();await expect(page.locator('#main-content h1')).toHaveText('Мои заявки');
  await expect(chat(page).getByRole('textbox',{name:'Ваш вопрос Jana'})).toHaveValue('Мой незаконченный вопрос');
  const bounds=await chat(page).boundingBox();expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(page.viewportSize()!.width+1);expect(bounds!.y+bounds!.height).toBeLessThanOrEqual(page.viewportSize()!.height+1);
  await page.screenshot({path:`test-results/jana-header-modal-${info.project.name}.png`,fullPage:true});
  await page.keyboard.press('Escape');await page.getByLabel('Меню профиля',{exact:true}).click();await page.getByRole('button',{name:'Выйти',exact:true}).click();
  await expect(launcher(page)).toHaveCount(0);await expect(page.locator('#jana-global-chat')).toHaveCount(0);await expect(page.getByRole('textbox',{name:'Ваш вопрос Jana'})).toHaveCount(0);
});

test('closing during inference keeps the answer and nested source Escape closes only the source',async({page})=>{
  let release!:()=>void;const held=new Promise<void>(resolve=>{release=resolve;});
  const calls=await portal(page,async route=>{await held;await reply(route,answer);});await page.goto('/');await open(page);
  await chat(page).getByRole('textbox',{name:'Ваш вопрос Jana'}).fill('Кто окончательно согласует отпуск?');
  await chat(page).getByRole('button',{name:'Отправить вопрос'}).click();
  await expect.poll(()=>calls.filter(c=>c.path==='/ai/ask').length).toBe(1);
  await chat(page).getByRole('button',{name:'Закрыть AI Jana'}).click();await toRequests(page);release();
  await open(page);await expect(chat(page).locator('.support-answer-text')).toHaveText(quote);
  expect(calls.filter(c=>c.path==='/ai/ask')).toHaveLength(1);
  await chat(page).getByRole('button',{name:source.title,exact:true}).click();
  const evidence=page.getByRole('dialog',{name:'Документ HR',exact:true});await expect(evidence.locator('blockquote')).toHaveText(quote);
  expect(calls.some(c=>c.path===`/ai/sources/${sourceId}?version=modal-snapshot`)).toBe(true);
  await page.keyboard.press('Escape');await expect(evidence).toHaveCount(0);await expect(chat(page)).toBeVisible();
  await expect(chat(page).getByRole('button',{name:source.title,exact:true})).toBeFocused();
  await page.keyboard.press('Escape');await expect(chat(page)).toBeHidden();await expect(launcher(page)).toBeFocused();
});

test('modal preserves failures, requires HR consent, and loads portal summary without a model request',async({page})=>{
  const calls=await portal(page,route=>route.request().postDataJSON().question==='Ошибка модели'?reply(route,{detail:'Jana AI is temporarily unavailable'},503):reply(route,{answer:'В базе нет подтверждённого ответа.',grounded:false,escalation_suggested:true,sources:[],mode:'refusal'}));
  await page.goto('/');await open(page);
  await chat(page).getByRole('button',{name:'Что требует внимания?'}).click();
  await expect(chat(page).locator('.hf-report')).toContainText('Мои заявки на согласовании');expect(calls.filter(c=>c.path==='/ai/ask')).toHaveLength(0);
  await expect(chat(page).locator('.support-message.summary')).toContainText('Без обращения к модели');
  await chat(page).getByRole('link',{name:'Заявка на отпуск',exact:true}).click();await expect(chat(page)).toBeHidden();await expect(page).toHaveURL(/\/requests$/);await open(page);
  await chat(page).getByRole('textbox',{name:'Ваш вопрос Jana'}).fill('Ошибка модели');await chat(page).getByRole('button',{name:'Отправить вопрос'}).click();
  await expect(chat(page).getByRole('alert')).toContainText('Локальная Jana сейчас недоступна');
  await page.keyboard.press('Escape');await open(page);await expect(chat(page).getByRole('textbox',{name:'Ваш вопрос Jana'})).toHaveValue('Ошибка модели');
  await chat(page).getByRole('textbox',{name:'Ваш вопрос Jana'}).fill('Неизвестный факт');await chat(page).getByRole('button',{name:'Отправить вопрос'}).click();
  await chat(page).getByRole('button',{name:'Передать вопрос в HR',exact:true}).click();
  const consent=page.getByRole('dialog',{name:'Передать вопрос в HR',exact:true});await expect(consent.getByRole('button',{name:'Отправить в HR',exact:true})).toBeDisabled();
  expect(calls.filter(c=>c.path==='/workspace/tickets')).toHaveLength(0);
  await consent.getByRole('checkbox').check();await consent.getByRole('button',{name:'Отправить в HR',exact:true}).click();
  await expect(page.getByRole('dialog',{name:'Обращение отправлено'})).toBeVisible();
  const sent=calls.filter(c=>c.path==='/workspace/tickets');expect(sent).toHaveLength(1);expect(sent[0].body.consent).toBe(true);
  await page.keyboard.press('Escape');await expect(chat(page)).toBeVisible();
});
