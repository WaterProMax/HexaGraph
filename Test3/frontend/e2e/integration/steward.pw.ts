import { expect, test } from '@playwright/test';

test('project steward prepares a plan, edits its schedule and reviews a project lesson', async ({ page, baseURL }) => {
  const origin = new URL(baseURL!).origin;
  await page.route('**/*', (route) => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/steward');
  await page.getByRole('button', { name: '填入课堂示例' }).click();
  await page.getByRole('button', { name: '开始需求分析' }).click();
  await expect(page).toHaveURL(/\/steward\/[^/]+$/);
  const gate = page.getByRole('region', { name: '当前确认点' });
  for (const heading of ['初步做法确认', '争议清单查看与裁决', '方案比选', '评审确认', 'SPEC基线确认', 'DESIGN基线确认']) {
    await expect(gate.getByRole('heading', { name: heading, exact: true })).toBeVisible();
    if (heading === '方案比选') {
      await expect(page.getByRole('radio', { name: /^方案 A/ })).toBeVisible();
      await expect(page.getByRole('radio', { name: /^方案 B/ })).toBeVisible();
      await page.getByRole('radio', { name: '融合两份方案后评审' }).check();
      await gate.getByRole('button', { name: '融合并评审' }).click();
      continue;
    }
    await gate.getByRole('button', { name: '确认并推进' }).click();
  }
  await expect(gate.getByRole('heading', { name: 'PLAN基线确认' })).toBeVisible();
  const chart = page.getByRole('region', { name: '甘特排期' });
  await expect(chart.getByRole('button').first()).toBeVisible();
  await chart.getByRole('button').first().click();
  const taskName = page.getByRole('textbox', { name: '任务名称' });
  await taskName.fill('演示：更新任务名称');
  await page.getByRole('button', { name: '保存并重新排期' }).click();
  await expect(chart.getByRole('button', { name: /演示：更新任务名称/ })).toBeVisible();
  await expect(taskName).toHaveValue('演示：更新任务名称');
  await expect(gate.getByRole('button', { name: '确认并推进' })).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath('steward-schedule.png'), fullPage: true });
  await page.setViewportSize({ width: 768, height: 900 });
  expect(await page.locator('.steward').evaluate((panel) => panel.scrollWidth - panel.clientWidth)).toBeLessThanOrEqual(1);
  await page.getByRole('button', { name: '项目经验', exact: true }).click();
  await page.getByRole('textbox', { name: '经验标题' }).fill('核对前置依赖');
  await page.getByRole('textbox', { name: '问题、做法与验证' }).fill('调整点数后检查甘特排期与关键路径。');
  await page.getByRole('button', { name: '提交审核' }).click();
  await page.getByRole('button', { name: '收录经验' }).click();
  await expect(page.getByText('已收录', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '项目经验', exact: true }).click();
  await expect(page.getByText('核对前置依赖', { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
