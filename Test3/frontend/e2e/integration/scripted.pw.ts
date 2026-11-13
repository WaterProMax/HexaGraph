import { test, expect } from '@playwright/test';

test('scripted HTTP backend: create, approve, pause, resume and confirm termination', async ({ page }) => {
  // No API response mocking here; only local browser traffic is allowed.
  await page.route('**/*', route => {
    const origin = new URL(route.request().url()).origin;
    return origin === 'http://127.0.0.1:5173' ? route.continue() : route.abort();
  });
  const errors: string[] = [];
  page.on('pageerror', err => errors.push(err.message));
  await page.goto('/workstation');
  await page.getByRole('textbox', { name: '项目名称', exact: true }).fill('离线集成验收');
  await page.getByRole('button', { name: /^启动/ }).click();
  await expect(page).toHaveURL(/\/workstation\/[^/]+$/);
  const id = new URL(page.url()).pathname.split('/').at(-1)!;
  const approve = page.getByRole('button', { name: '批准并推进' });
  await expect(approve).toBeEnabled();
  const response = page.waitForResponse(r => /\/gates\/.*\/resolve$/.test(r.url()) && r.request().method() === 'POST');
  await approve.click();
  expect((await response).ok()).toBeTruthy();
  await expect(page.locator('.topbar-right')).toContainText('阶段 1');
  await page.getByRole('button', { name: '暂停', exact: true }).click();
  await expect(page.locator('.topbar-right')).toContainText('已暂停');
  await page.getByRole('button', { name: '恢复', exact: true }).click();
  await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('scripted-workstation.png'), fullPage: true });
  await page.goto(`/runs/${id}`);
  const button = page.getByRole('button', { name: '终止运行', exact: true });
  await expect(button).toBeEnabled();
  page.once('dialog', dialog => dialog.dismiss());
  await button.click();
  await expect(button).toBeEnabled();
  page.once('dialog', dialog => dialog.accept());
  await button.click();
  await expect(button).toBeDisabled();
  await expect(page.getByText(/状态 terminated/)).toBeVisible();
  expect(errors).toEqual([]);
});
