import {test,expect,type Page} from '@playwright/test';
const hr='81000000-0000-4000-8000-000000000001',worker='81000000-0000-4000-8000-000000000002',request='81000000-0000-4000-8000-000000000003',course='81000000-0000-4000-8000-000000000004';
const stamp='2026-10-17T10:00:00Z';
async function fixture(page:Page){
 const profile={id:hr,employee_code:'TEST-HR',full_name:'Тестовый HR',email:'hr@example.test',company:'PostTech',job_title:'HR',department:'Тест',manager_id:null,hired_at:'2025-01-01',vacation_days_remaining:24,role:'hr_admin',external_source:'test',created_at:stamp,updated_at:stamp};
 const person={...profile,id:worker,full_name:'Сотрудник с очень длинными фамилией именем и отчеством',role:'worker',employee_code:'TEST-001',email:'worker@example.test'};
 const row={id:request,employee_id:worker,request_type:'leave',status:'approved',start_date:'2026-11-01',end_date:'2026-11-03',amount:null,comment:'',reviewer_comment:null,reviewed_by:hr,reviewed_at:stamp,created_at:stamp,updated_at:stamp,can_review:false,approvers:[{id:hr,full_name:profile.full_name,role:'hr_admin'}]};
 let state='awaiting_hr';const writes:{path:string;body:any}[]=[];
 await page.addInitScript(()=>sessionStorage.setItem('jana.hr.session.v1',JSON.stringify({user_id:'test',email:'hr@example.test',access_token:'test',refresh_token:'test',token_type:'bearer',expires_in:3600,expires_at:Date.now()+3600000})));
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api/v1','');const body=req.postData()?req.postDataJSON():null;
  const reply=(data:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  if(req.method()!=='GET')writes.push({path,body});
  if(path==='/profile')return reply(profile);
  if(path==='/team')return reply([profile,person]);
  if(path==='/workspace/fulfillment')return reply([{request_id:request,updated_at:stamp,hr_requests:{...row,employee_profiles:{full_name:person.full_name}}}]);
  if(path===`/workspace/fulfillment/${request}`){if(req.method()==='POST')state='completed';return reply({status:state,note:'',document_reference:state==='completed'?'Приказ № 123':null,completed_at:stamp,can_send:false,deliveries:[],events:[]});}
  if(path===`/requests/${request}`)return reply({...row,fulfillment:{status:state}});
  if(path.endsWith('/history'))return reply([]);
  if(path==='/workspace/employee-import/preview')return reply({id:request,filename:'test.csv',rows:Array.from({length:45},(_,i)=>({line:i+2,full_name:`Очень длинное имя сотрудника ${i+1}`,employee_code:`TEST-${i}`,email:`test.employee.${i}@example.test`,action:'update',changes:[{field:'department',before:'Склад',after:'Департамент международных перевозок и логистики'}]})),errors:[]});
  if(path.endsWith('/apply'))return reply({updated:45,invitations:[]});
  if(path==='/workspace/tracks')return reply(req.method()==='GET'?[]:{id:request});
  if(path==='/academy/courses')return reply([{id:course,title:'Безопасная работа в распределительном центре и международная логистика',description:'Test',duration_minutes:10}]);
  if(path==='/workspace/workflow-policy')return reply({enabled:true,remind_hours:48,escalate_hours:96,course_notice_days:3,last_run_at:new Date().toISOString()});
  if(path==='/workspace/workflow-policy/run')return reply({sent:0});
  if(path==='/workspace/summary')return reply({as_of:stamp,sections:[{title:'Ждут вашего решения',count:1,href:'/requests?scope=review',items:[{label:'Отпуск · с 2026-10-17',href:`/requests/${request}`}]}]});
  return reply([]);
 });return {writes};
}
async function noOverflow(page:Page){expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);}

test('HR queue opens a document step; completing it requires a reference',async({page})=>{
 const {writes}=await fixture(page);await page.goto('/hr-workflow');await page.getByRole('link',{name:'Открыть заявку'}).click();
 await expect(page.getByRole('heading',{name:'Ожидает оформления HR'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Подтвердить оформление'})).toBeDisabled();
 await page.getByLabel('Номер оформленного документа').fill('Приказ № 123');
 await noOverflow(page);await page.getByRole('button',{name:'Подтвердить оформление'}).click();
 await expect(page.getByRole('heading',{name:'Документ оформлен'})).toBeVisible();
 expect(writes.filter(w=>w.path.includes('/fulfillment/'))).toHaveLength(1);
});

test('import needs preview, shows changed values and paginates long lists',async({page})=>{
 const {writes}=await fixture(page);await page.goto('/hr-workflow?tab=import');
 await page.getByLabel('Файл сотрудников').setInputFiles({name:'test.csv',mimeType:'text/csv',buffer:Buffer.from('employee_code,full_name\n0001,Test')});
 expect(writes).toHaveLength(0);await page.getByRole('button',{name:'Проверить файл'}).click();
 await expect(page.getByRole('heading',{name:'Предпросмотр'})).toBeVisible();
 expect(writes).toHaveLength(1);await expect(page.locator('.hf-preview article')).toHaveCount(20);
 await page.locator('.hf-preview details').first().locator('summary').click();await expect(page.locator('.hf-preview').first()).toContainText('Департамент международных перевозок');
 await noOverflow(page);await page.getByRole('button',{name:'Далее',exact:true}).click();await expect(page.locator('.hf-preview article').first()).toContainText('сотрудника 21');
 await page.getByRole('button',{name:'Применить импорт'}).click();await expect(page.getByRole('heading',{name:'Импорт завершён'})).toBeVisible();expect(writes).toHaveLength(2);
});

test('long onboarding form and reminder settings fit narrow screens',async({page},info)=>{
 await fixture(page);if(info.project.name==='mobile')await page.setViewportSize({width:320,height:780});
 await page.goto('/hr-workflow?tab=tracks');await page.getByRole('button',{name:'Новая траектория'}).click();
 await page.getByLabel('Название',{exact:true}).fill('Адаптация сотрудника международного распределительного центра');
 await page.getByLabel('Курс шага 1',{exact:true}).selectOption(course);
 for(let i=0;i<6;i++)await page.getByRole('button',{name:'Добавить шаг'}).click();
 await noOverflow(page);await expect(page.getByRole('button',{name:'Создать траекторию',exact:true})).toBeEnabled();
 await page.screenshot({path:`test-results/hr-track-${info.project.name}.png`,fullPage:true});
 await page.getByRole('button',{name:'Закрыть',exact:true}).click();
 await page.getByRole('link',{name:'Напоминания',exact:true}).click();await expect(page.getByText('Планировщик работает',{exact:false})).toBeVisible();
 await page.getByLabel('Передать задержку HR через, ч.').fill('24');await expect(page.getByRole('button',{name:'Сохранить',exact:true})).toBeDisabled();await noOverflow(page);
});

test('Jana gives a scoped actionable report',async({page})=>{
 const {writes}=await fixture(page);await page.goto('/jana');await page.getByRole('button',{name:'Что требует внимания?'}).click();
 await expect(page.locator('.hf-report')).toContainText('Ждут вашего решения');expect(writes).toHaveLength(0);await expect(page.locator('.support-message.summary')).toContainText('Без обращения к модели');
 await expect(page.locator('.hf-report').getByRole('link',{name:'Отпуск · с 2026-10-17'})).toHaveAttribute('href',`/requests/${request}`);await noOverflow(page);
});
