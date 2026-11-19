import { test, expect } from '@playwright/test';

test('DeepSeek without a key: real HTTP import fails honestly with no plan or fallback', async ({ page }) => {
  await page.route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:5173' ? route.continue() : route.abort());
  await page.goto('/deepseek');
  await page.getByRole('textbox', { name: '设计规格原文', exact: true }).fill('学生查看自习室座位，使用 Python，必须显示剩余数量和更新时间。');
  await page.getByRole('button', { name: '调用 DeepSeek 并检查', exact: true }).click();
  await expect(page).toHaveURL(/\/deepseek\/[^/]+$/);
  await expect(page.getByText(/下一步：检查配置，不改文档/)).toBeVisible({ timeout: 20000 });
  const id = page.url().split('/').at(-1)!;
  const arts = await (await page.request.get(`/api/runs/${id}/artifacts`)).json();
  expect(arts.design_input_status).toBe('failed');
  expect(arts.design_input_error_category).toBe('auth');
  expect(arts.provenance.mode).toBe('deepseek');
  expect(arts.plan).toBeUndefined();
  const tasks = await (await page.request.get(`/api/runs/${id}/tasks`)).json();
  expect(tasks).toEqual([]);
  await expect(page.getByRole('button', { name: '批准并推进', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '修改原文后重新提交', exact: true })).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath('deepseek-no-key.png'), fullPage: true });
});
