import { expect, test } from '@playwright/test';
import { mockPlans } from './fixtures/calendar-plans';

for (const role of ['manager', 'hr_admin'] as const) {
  test(`${role}: team calendar shows each employee and opens their course`, async ({
    page,
  }, info) => {
    if (info.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 844 });
    const state = await mockPlans(page, role);
    const course = {
      ...state.courses[0].course!,
      course_type: 'external' as const,
      provider: 'Яндекс Практикум',
      external_url: 'https://start.practicum.yandex/excel-for-work/',
      title: 'Excel для работы',
    };
    state.courses[0].course = course;
    for (const [index, name] of ['Алия Серикова', 'Дана Омарова'].entries()) {
      const id = `80000000-0000-4000-8000-00000000000${index}`;
      state.teamCourses.push({
        ...state.courses[0],
        id: `team-${index}`,
        employee_id: id,
        course,
        employee: { id, full_name: name, department: 'Логистика', job_title: 'Специалист' },
      });
    }
    state.active.employee_id = state.teamCourses[0].employee_id;
    await page.goto('/calendar?date=2026-11-01');
    await page.locator('.cal-scope').getByRole('button', { name: 'Команда', exact: true }).click();
    const details = page.getByRole('region', { name: 'События дня' });
    await expect(details.locator('.cal-selected-course')).toHaveCount(2);
    await expect(details).toContainText('Алия Серикова');
    await expect(details).toContainText('Дана Омарова');
    await expect(details.locator('.cal-selected-event')).toHaveCount(3);
    const alia = details.locator('.cal-selected-course').filter({ hasText: 'Алия Серикова' });
    await alia.getByRole('link', { name: 'Открыть курс' }).click();
    const modal = page.getByRole('dialog');
    await expect(modal).toContainText('Алия Серикова');
    await expect(modal.getByRole('link', { name: 'Открыть на площадке' })).toHaveAttribute(
      'href',
      course.external_url,
    );
    await expect(modal.getByRole('button', { name: 'Сохранить прогресс' })).toHaveCount(0);
    state.teamCourses[0].progress_percent = 70;
    await expect(modal.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '70');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: info.outputPath('team-external-course.png') });
    await page.goBack();
    await expect(
      page.locator('.cal-scope').getByRole('button', { name: 'Команда', exact: true }),
    ).toHaveClass('active');
    state.teamCourses[0].status = 'completed';
    await expect(details.locator('.cal-selected-course')).toHaveCount(1);
    state.teamCourses[1].due_on = '2026-11-02';
    await expect(details.locator('.cal-selected-course')).toHaveCount(0);
    await expect(page.locator('.cal-day[data-day="2026-11-02"]')).toHaveClass(/has-course/);
  });
}

test('employee records external progress and confirms completion without a quiz', async ({
  page,
}, info) => {
  if (info.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 844 });
  const state = await mockPlans(page, 'worker');
  const assignment = state.courses[0];
  Object.assign(assignment.course!, {
    course_type: 'external',
    provider: 'Яндекс Практикум',
    external_url: 'https://start.practicum.yandex/excel-for-work/',
    duration_minutes: 0,
  });
  await page.goto(`/academy?course=${assignment.course_id}`);
  const modal = page.getByRole('dialog');
  await expect(modal.getByRole('button', { name: 'Перейти к тесту' })).toHaveCount(0);
  await modal.getByLabel('Пройдено, %', { exact: true }).fill('65');
  await modal.getByRole('button', { name: 'Сохранить прогресс' }).click();
  await expect(modal.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '65');
  await page.reload();
  await expect(modal.getByLabel('Пройдено, %', { exact: true })).toHaveValue('65');
  await modal.getByLabel('Пройдено, %', { exact: true }).fill('100');
  await expect(modal.getByRole('button', { name: 'Сохранить прогресс' })).toBeDisabled();
  await modal.getByLabel('Я завершил курс на площадке').check();
  await modal.getByRole('button', { name: 'Сохранить прогресс' }).click();
  await expect(modal.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  await expect(modal.getByLabel('Пройдено, %', { exact: true })).toHaveCount(0);
  expect(assignment.score_percent).toBeNull();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('external-completed.png') });
});

test('employee adds an external course from the catalog', async ({ page }) => {
  const state = await mockPlans(page, 'worker');
  const course = {
    ...state.courses[0].course!,
    course_type: 'external',
    provider: 'Яндекс Практикум',
    external_url: 'https://start.practicum.yandex/excel-for-work/',
  };
  let enrolled = false;
  await page.route(`**/api/v1/academy/courses/${course.id}`, (route) =>
    route.fulfill({
      json: {
        ...course,
        quiz: [],
        material_markdown: '',
        active: true,
        assignment: enrolled ? state.courses[0] : null,
      },
    }),
  );
  await page.route(`**/api/v1/academy/courses/${course.id}/enroll`, (route) => {
    enrolled = true;
    return route.fulfill({ json: state.courses[0] });
  });
  await page.goto(`/academy?tab=all&course=${course.id}`);
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('button', { name: 'Добавить в моё обучение' }).click();
  await expect(dialog.getByLabel('Пройдено, %', { exact: true })).toBeVisible();
  expect(enrolled).toBe(true);
});

test('HR creates an external course without inventing a test', async ({ page }, info) => {
  if (info.project.name === 'mobile') await page.setViewportSize({ width: 320, height: 844 });
  await mockPlans(page, 'hr_admin');
  let saved: any;
  await page.route('**/api/v1/workspace/courses', (route) => {
    if (route.request().method() === 'POST') {
      saved = route.request().postDataJSON();
      return route.fulfill({
        json: { ...saved.data, id: saved.id, revision: 1, version: 1, publication_state: 'draft' },
      });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/course-editor');
  await page.getByRole('button', { name: 'Создать курс', exact: true }).click();
  await page.getByLabel('Площадка', { exact: true }).fill('Яндекс Практикум');
  await page
    .getByLabel('Ссылка на курс', { exact: true })
    .fill('https://start.practicum.yandex/excel-for-work/');
  await page.getByLabel('Название курса', { exact: true }).fill('Excel для работы');
  await expect(page.getByLabel('Материал курса', { exact: true })).toHaveCount(0);
  await expect(page.getByText('Проверка знаний', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: /Сохранить черновик/ }).click();
  await expect.poll(() => saved?.data?.course_type).toBe('external');
  expect(saved.data.quiz).toEqual([]);
  expect(saved.data.external_url).toBe('https://start.practicum.yandex/excel-for-work/');
});
