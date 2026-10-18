const {chromium, request, expect} = require('../frontend/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const data = JSON.parse(fs.readFileSync(path.join(root, '.local/activation-credentials.json'), 'utf8'));
const baseURL = 'http://127.0.0.1:8000';
const labels = {worker:'Сотрудник', manager:'Руководитель', director:'Директор', hr_admin:'HR-администратор'};
const results = [];
let completed = false;

(async () => {
 const browser = await chromium.launch({headless:true, executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH || 'C:/Users/juven/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 const fixture = JSON.parse(fs.readFileSync(path.join(root,'.local/scenario-credentials.json'),'utf8'));
 const login = await request.newContext({baseURL});
 const response = await login.post('/api/v1/auth/login',{data:{email:fixture.hr.email,password:fixture.hr.password}});
 if (!response.ok()) throw Error('HR fixture login failed');
 const hrSession = await response.json(); await login.dispose();
 const hrViews = [];
 try {
  for (const width of [1440,390]) {
   const context = await browser.newContext({viewport:{width,height:900},isMobile:width<500,hasTouch:width<500});
   await context.addInitScript(session => sessionStorage.setItem('jana.hr.session.v1',JSON.stringify({...session,expires_at:Date.now()+session.expires_in*1000})),hrSession);
   const page = await context.newPage(); await page.goto(baseURL+'/team');
   await page.getByRole('button',{name:'Пригласить сотрудника',exact:true}).click();
   await page.getByRole('button',{name:'Выданные',exact:true}).click();
   await expect(page.locator('.invite-list article').filter({hasText:data.accounts[0].email})).toContainText('Ожидает активации');
   hrViews.push({page,context,width,navigations:0});
   page.on('framenavigated', frame => {if(frame === page.mainFrame()) hrViews.find(v=>v.page===page).navigations++;});
  }
  for (const account of data.accounts) {
   for (const width of [1440,390]) {
    const context = await browser.newContext({viewport:{width,height:900},isMobile:width<500,hasTouch:width<500,locale:'ru-RU'});
    try {
     const page = await context.newPage();
     await page.goto(baseURL+'/login');
     if (width === 1440) {
      await page.getByRole('button',{name:'Активировать приглашение',exact:true}).click();
      await page.getByLabel('Код приглашения',{exact:true}).fill(account.code);
      await page.getByRole('button',{name:'Продолжить',exact:true}).click();
      await expect(page.getByText('HR назначил вам роль:',{exact:false})).toContainText(labels[account.role]);
      await expect(page.getByRole('radio')).toHaveCount(0);
      await expect(page.getByLabel('Email',{exact:true})).toHaveAttribute('readonly','');
      await page.getByRole('button',{name:'Уже есть код из письма',exact:true}).click();
      await page.getByLabel('Код подтверждения',{exact:true}).fill(account.otp);
      await page.getByRole('button',{name:'Подтвердить',exact:true}).click();
      await expect(page.getByText('Ваш аккаунт активирован.',{exact:false})).toBeVisible({timeout:20000});
      await expect(page.getByText('Ваша роль:',{exact:false})).toContainText(labels[account.role]);
      for (const view of hrViews) {
       await expect(view.page.locator('.invite-list article').filter({hasText:account.email})).toContainText('Активировано',{timeout:20000});
      }
      await page.getByRole('button',{name:'Перейти на главную',exact:true}).click();
     } else {
      await page.getByLabel('Рабочая почта',{exact:true}).fill(account.email);
      await page.getByLabel('Пароль',{exact:true}).fill(account.password);
      await page.getByRole('button',{name:'Войти',exact:true}).click();
     }
     await expect(page.getByRole('heading',{name:'Мой кабинет',exact:true})).toBeVisible({timeout:20000});
     const session = await page.evaluate(() => JSON.parse(sessionStorage.getItem('jana.hr.session.v1')));
     const client = await request.newContext({baseURL,extraHTTPHeaders:{Authorization:`Bearer ${session.access_token}`}});
     try {
      const profileResponse = await client.get('/api/v1/profile');
      const profile = await profileResponse.json();
      if (!profileResponse.ok() || profile.role !== account.role || profile.email !== account.email) throw Error('Assigned role mismatch');
      const admin = await client.get('/api/v1/auth/invitations');
      if (admin.status() !== (account.role === 'hr_admin' ? 200 : 403)) throw Error('Role permissions mismatch');
     } finally { await client.dispose(); }
     if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)) throw Error('Mobile overflow');
     results.push({role:account.role,width,activationOrLogin:true,assignedRole:true,permissions:true,noRoleChooser:true});
     console.log(JSON.stringify(results.at(-1)));
    } finally { await context.close(); }
   }
  }
  for (const view of hrViews) {
   await view.page.getByRole('button',{name:'Закрыть',exact:true}).click();
   await view.page.getByLabel('Поиск сотрудника',{exact:true}).fill('ACTCHECK-'+data.run_id);
   await expect(view.page.locator('.people-row')).toHaveCount(4,{timeout:20000});
   if(view.navigations) throw Error('HR page reloaded');
   if(await view.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('HR overflow');
  }
  completed = true;
 } finally {
  fs.writeFileSync(path.join(root,'.local/invitation-activation-report.json'),JSON.stringify({at:new Date().toISOString(),results,hrViews:hrViews.map(v=>({width:v.width,navigations:v.navigations})),mail:'Real invitation sends to Resend simulated-delivery inboxes',otp:'Real Supabase OTP generated by admin for disposable fixtures; inbox receipt is a separate check',status:completed?'passed':'failed'},null,2));
  await browser.close();
 }
})().catch(() => {console.error('Invitation activation failed; no credentials printed.');process.exitCode=1;});
