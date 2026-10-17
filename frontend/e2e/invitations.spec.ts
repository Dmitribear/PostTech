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
 await expect(page.getByRole('combobox',{name:'Роль',exact:true}).getByRole('option',{name:'Директор',exact:true})).toHaveCount(1);
 await page.getByRole('combobox',{name:'Роль',exact:true}).selectOption('manager');
 await page.getByRole('button',{name:'Пригласить по почте',exact:true}).click();
 await expect(page.getByRole('status')).toContainText('Почтовый сервис отклонил письмо');
 expect(payload.role).toBe('manager');
 await expect(page.getByRole('button',{name:/Повторить через/})).toBeDisabled();
 await page.getByText('Передать код вручную',{exact:true}).click();
 await expect(page.getByLabel('Код приглашения',{exact:true})).toHaveValue('JP-private-invitation');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
});


test('simplified demo still offers the director and top-right Jana', async ({page}) => {
 await page.goto('/login');
 await expect(page.getByRole('button',{name:'Открыть AI Jana',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'Демо-вход',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Демонстрация портала',exact:true})).toBeVisible();
 await page.getByRole('radio',{name:/^Директор/}).check();
 await page.getByRole('button',{name:'Открыть демо',exact:true}).click();
 const launcher=page.getByRole('button',{name:'Открыть AI Jana',exact:true});
 await expect(launcher).toBeVisible();
 const bounds=await launcher.boundingBox();expect(bounds!.y).toBeLessThan(80);
 await launcher.click();
 await expect(page.getByRole('dialog',{name:'Чат с AI Jana',exact:true})).toBeVisible();
});
