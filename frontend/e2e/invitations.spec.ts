import {test,expect} from '@playwright/test';

test('registration shows HR-assigned role without a role chooser',async({page})=>{
 await page.route('**/api/v1/auth/invitations/check',r=>r.fulfill({json:{email:'invited@example.test',role:'manager',department:'Логистика',expires_at:'2026-12-01T00:00:00Z'}}));
 let payload:any;
 await page.route('**/api/v1/auth/register',r=>{payload=r.request().postDataJSON();return r.fulfill({json:{email:'invited@example.test',email_confirmation_required:true}});});
 await page.goto('/login');
 await page.getByRole('button',{name:'Активировать приглашение',exact:true}).click();
 await page.getByLabel('Код приглашения',{exact:true}).fill('JP-invitation-code');
 await page.getByRole('button',{name:'Продолжить',exact:true}).click();
 await expect(page.getByText('HR назначил вам роль:',{exact:false})).toContainText('Руководитель');
 await expect(page.getByRole('radio')).toHaveCount(0);
 await expect(page.getByLabel('Email',{exact:true})).toHaveAttribute('readonly','');
 await page.getByLabel('Имя',{exact:true}).fill('Алексей');
 await page.getByLabel('Фамилия',{exact:true}).fill('Ким');
 await page.getByLabel('Пароль',{exact:true}).fill('Example-password9');
 await page.getByRole('button',{name:'Создать аккаунт',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Проверьте почту',exact:true})).toBeVisible();
 expect(payload.role).toBeUndefined();expect(payload.email).toBeUndefined();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
});

test('HR assigns role and sees honest failed email state with retry',async({page})=>{
 const stamp='2026-10-17T10:00:00Z',id='81000000-0000-4000-8000-000000000001';
 const profile={id,employee_code:'TEST-HR',full_name:'Тестовый HR',email:'hr@example.test',company:'PostTech',job_title:'HR',department:'Тест',manager_id:null,hired_at:'2025-01-01',vacation_days_remaining:24,role:'hr_admin',external_source:'test',created_at:stamp,updated_at:stamp};
 await page.addInitScript(()=>sessionStorage.setItem('jana.hr.session.v1',JSON.stringify({user_id:'test',email:'hr@example.test',access_token:'test',refresh_token:'test',token_type:'bearer',expires_in:3600,expires_at:Date.now()+3600000})));
 let payload:any;
 await page.route('**/api/v1/**',async r=>{
  const path=new URL(r.request().url()).pathname;
  if(path.endsWith('/profile'))return r.fulfill({json:profile});
  if(path.endsWith('/team'))return r.fulfill({json:[profile]});
  if(path.endsWith('/auth/invitations')&&r.request().method()==='POST'){
   payload=r.request().postDataJSON();return r.fulfill({json:{...payload,id,invitation_code:'JP-private-invitation',email_status:'failed',expires_at:'2026-12-01T00:00:00Z'}});
  }
  return r.fulfill({json:[]});
 });
 await page.goto('/team');
 await page.getByRole('button',{name:/Пригласить/}).click();
 await page.getByLabel('Рабочая почта',{exact:true}).fill('invited@example.test');
 await page.getByLabel('Табельный номер',{exact:true}).fill('TEST-001');
 await page.getByLabel('Должность',{exact:true}).fill('Начальник склада');
 await page.getByRole('combobox',{name:'Роль',exact:true}).selectOption('manager');
 await page.getByRole('button',{name:'Пригласить по почте',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Почтовый сервис отклонил письмо');
 expect(payload.role).toBe('manager');
 await expect(page.getByRole('button',{name:/Повторить через/})).toBeDisabled();
 await page.getByText('Передать код вручную',{exact:true}).click();
 await expect(page.getByLabel('Код приглашения',{exact:true})).toHaveValue('JP-private-invitation');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
});

test('HR sees activation and the new employee without reloading', async ({page}) => {
 const stamp = '2026-10-18T10:00:00Z';
 const profile = {id:'81000000-0000-4000-8000-000000000001',employee_code:'TEST-HR',full_name:'Тестовый HR',email:'hr@example.test',company:'PostTech',job_title:'HR',department:'Тест',manager_id:null,hired_at:'2025-01-01',vacation_days_remaining:24,role:'hr_admin',external_source:'test',created_at:stamp,updated_at:stamp};
 let activated = false;
 await page.addInitScript(() => sessionStorage.setItem('jana.hr.session.v1', JSON.stringify({user_id:'test',email:'hr@example.test',access_token:'test',refresh_token:'test',token_type:'bearer',expires_in:3600,expires_at:Date.now()+3600000})));
 await page.route('**/api/v1/**', async route => {
  const pathname = new URL(route.request().url()).pathname;
  if (pathname.endsWith('/profile')) return route.fulfill({json:profile});
  if (pathname.endsWith('/team')) return route.fulfill({json:activated ? [profile,{...profile,id:'81000000-0000-4000-8000-000000000002',full_name:'Новый Сотрудник',email:'joined@example.test',role:'worker'}] : [profile]});
  if (pathname.endsWith('/auth/invitations')) return route.fulfill({json:[{id:'81000000-0000-4000-8000-000000000003',email:'joined@example.test',role:'worker',department:'Тест',expires_at:'2099-12-01T00:00:00Z',consumed_at:activated?stamp:null,revoked_at:null,email_status:'accepted'}]});
  return route.fulfill({json:[]});
 });
 await page.goto('/team');
 await page.getByRole('button',{name:'Пригласить сотрудника',exact:true}).click();
 await page.getByRole('button',{name:'Выданные',exact:true}).click();
 const invitation = page.locator('.invite-list article').filter({hasText:'joined@example.test'});
 await expect(invitation).toContainText('Ожидает активации');
 let navigations = 0;
 page.on('framenavigated', frame => {if (frame === page.mainFrame()) navigations++;});
 activated = true;
 await expect(invitation).toContainText('Активировано');
 await expect(invitation.getByRole('button')).toHaveCount(0);
 await page.getByRole('button',{name:'Закрыть',exact:true}).click();
 await expect(page.getByText('Новый Сотрудник',{exact:true})).toBeVisible();
 expect(navigations).toBe(0);
 expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
});
