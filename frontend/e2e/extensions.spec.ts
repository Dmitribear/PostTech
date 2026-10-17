import {expect,test,type Page} from '@playwright/test';

const employee='80000000-0000-4000-8000-000000000001';
const courseId='80000000-0000-4000-8000-000000000002';
const eventId='80000000-0000-4000-8000-000000000003';
const stamp='2026-10-17T10:00:00Z';
async function fixture(page:Page){
 const profile={id:employee,employee_code:'TEST-HR',full_name:'Тестовый HR',email:'hr@example.test',company:'PostTech',job_title:'HR',department:'Тест',manager_id:null,hired_at:'2025-01-01',vacation_days_remaining:24,role:'hr_admin',external_source:'test',created_at:stamp,updated_at:stamp};
 const assignment={id:eventId,employee_id:employee,course_id:courseId,assigned_by:employee,status:'in_progress',progress_percent:45,score_percent:null,assigned_at:stamp,completed_at:null,completed_lesson_ids:['first'],attempt_count:0};
 const course={id:courseId,title:'Безопасная работа',description:'Два коротких урока',duration_minutes:10,material_markdown:'Введение в курс',passing_score:80,active:true,created_at:stamp,quiz:[{id:'q1',prompt:'Как поступить?',options:['Верно','Неверно']}],lessons:[{id:'first',title:'Первый урок',material_markdown:'Первый материал'},{id:'second',title:'Второй урок',material_markdown:'Материал второго урока'}],assignment};
 const article={id:courseId,title:'Отпуска',content:'Проверенный текст политики. '.repeat(50),source_title:'Положение об отпусках',source_url:null,keywords:['отпуск'],revision:1,version:'1',draft:null,active:true,editorial_state:'legacy',review_due_at:null};
 const writes:{path:string;body:unknown}[]=[];
 await page.addInitScript(()=>sessionStorage.setItem('jana.hr.session.v1',JSON.stringify({user_id:'test',email:'hr@example.test',access_token:'test',refresh_token:'test',token_type:'bearer',expires_in:3600,expires_at:Date.now()+3600000})));
 await page.route('**/api/v1/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname.replace('/api/v1','');
  const reply=(data:unknown,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  if(req.method()!=='GET')writes.push({path,body:req.postData()?req.postDataJSON():null});
  if(path==='/profile')return reply(profile);
  if(path==='/team')return reply([profile]);
  if(path==='/workspace/knowledge')return reply(req.method()==='GET'?[article]:article);
  if(path.endsWith('/history'))return reply([]);
  if(path==='/workspace/integrations')return reply({connected:{'1c':false,documentolog:false},events:[{id:eventId,destination:'1c',aggregate_id:courseId,status:'dead',attempts:8,last_error:'HTTP 503',next_attempt_at:stamp,created_at:stamp}]});
  if(path.endsWith('/retry'))return reply({queued:true});
  if(path==='/workspace/leave-balance')return reply({employee_id:employee,official_days:24,pending_days:4,approved_unreconciled_days:5,available_days:15,request_days:4,holds:[{request_id:courseId,days:5,state:'approved'}]});
  if(path==='/requests/routing')return reply({can_submit:true,route:'hr',approvers:[{id:eventId,full_name:'Другой HR',role:'hr_admin'}],today:'2026-10-17',policy:'calendar_days'});
  if(path===`/academy/courses/${courseId}`)return reply(course);
  if(path==='/academy/courses')return reply([course]);
  if(path==='/academy/my-courses')return reply([{...assignment,course}]);
  if(path.endsWith('/lessons/second/complete')){assignment.completed_lesson_ids=['first','second'];assignment.progress_percent=90;return reply(assignment);}
  if(path.endsWith('/progress'))return reply(assignment);
  return reply([]);
 });
 return {writes};
}
async function noOverflow(page:Page){expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);}

test('home uses available leave balance and shows an honest unavailable state',async({page})=>{
 await fixture(page);await page.goto('/');
 await expect(page.locator('.desk-leave-copy')).toContainText('15 дн. доступно');
 await expect(page.getByRole('link',{name:'Продолжить',exact:true})).toHaveAttribute('href',`/academy?course=${courseId}`);
 await page.route('**/workspace/leave-balance',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Unavailable'})}));
 await page.reload();
 await expect(page.locator('.desk-leave-copy')).toContainText('Баланс недоступен');
 await expect(page.locator('.desk-leave-copy')).not.toContainText('24');
 await expect(page.getByRole('link',{name:'Оформить отпуск',exact:true})).toBeVisible();
 await noOverflow(page);
});

test('HR reviews long knowledge text before publishing and editor fits mobile',async({page},info)=>{
 const {writes}=await fixture(page);await page.goto('/operations');
 await page.getByRole('button',{name:'Проверить и опубликовать',exact:true}).click();
 const dialog=page.getByRole('dialog');await expect(dialog).toContainText('Положение об отпусках');
 expect(writes).toHaveLength(0);await dialog.getByLabel('Следующая проверка').fill('2030-12-01');
 await noOverflow(page);await page.screenshot({path:`test-results/knowledge-${info.project.name}.png`,fullPage:true});
 await dialog.getByRole('button',{name:'Подтвердить и опубликовать'}).click();
 expect(writes[0].body).toMatchObject({action:'approve',revision:1,due:'2030-12-01'});
 await page.getByRole('button',{name:'Редактировать',exact:true}).click();
 await page.getByLabel('Текст для Jana').fill('Обновлённый черновик для следующей проверки');
 await page.getByRole('button',{name:'Сохранить черновик'}).click();
 expect(writes.at(-1)?.body).toMatchObject({action:'save',data:{content:'Обновлённый черновик для следующей проверки'}});
});

test('integration failure can be queued without claiming external connection',async({page},info)=>{
 const {writes}=await fixture(page);await page.goto('/operations?tab=integrations');
 await expect(page.getByText('Не подключено — события сохраняются',{exact:true})).toHaveCount(2);
 await expect(page.getByText('HTTP 503',{exact:true})).toBeVisible();await noOverflow(page);
 await page.screenshot({path:`test-results/integrations-${info.project.name}.png`,fullPage:true});
 await page.getByRole('button',{name:'Вернуть в очередь'}).click();
 expect(writes).toEqual([{path:`/workspace/integrations/${eventId}/retry`,body:null}]);
});

test('course resumes first incomplete lesson and requires completion before quiz',async({page},info)=>{
 const {writes}=await fixture(page);await page.goto(`/academy?course=${courseId}`);
 const dialog=page.getByRole('dialog');await expect(dialog.getByRole('heading',{name:'Второй урок',exact:true})).toBeVisible();
 await expect(dialog.getByRole('button',{name:'Перейти к тесту'})).toBeDisabled();await noOverflow(page);
 await page.screenshot({path:`test-results/lessons-${info.project.name}.png`,fullPage:true});
 await dialog.getByRole('button',{name:'Завершить урок',exact:true}).click();
 await expect(dialog.getByRole('button',{name:'Перейти к тесту'})).toBeEnabled();
 await page.reload();await expect(page.getByRole('dialog')).toContainText('Пройдено уроков: 2 / 2');
 await page.getByRole('button',{name:'Перейти к тесту'}).click();await expect(page.getByText('Как поступить?',{exact:false})).toBeVisible();
 expect(writes[0].path).toBe(`/workspace/courses/${courseId}/lessons/second/complete`);
});

test('leave form blocks over-budget dates before sending and explains reservations',async({page})=>{
 const {writes}=await fixture(page);await page.goto('/requests/new?type=leave&start=2030-11-01&end=2030-11-20');
 await expect(page.getByText('Недостаточно дней для выбранного периода')).toBeVisible();
 await expect(page.getByRole('button',{name:'Продолжить',exact:true})).toBeDisabled();
 await expect(page.getByRole('region',{name:'Расчёт отпуска'})).toContainText('Одобрено, до сверки');
 expect(writes).toHaveLength(0);await noOverflow(page);
});
