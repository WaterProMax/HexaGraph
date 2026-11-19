import { test, expect } from './mock-api';

test('classroom: discussion, four human gates, parallel join, refresh and three resets', async ({ page, apiMock }) => {
  await page.goto('/workstation/static-classroom');
  await expect(page.getByTestId('static-demo-provenance')).toContainText('不调用真实模型');
  await page.getByRole('button', { name: '开始静态演示', exact: true }).click();
  const next = page.getByRole('button', { name: '下一步', exact: true });
  for (let i = 0; i < 10; i++) { await expect(next).toBeEnabled(); await next.click(); }
  await expect(page.getByTestId('static-gate')).toContainText('讨论结论确认');
  await expect(next).toBeDisabled();
  await expect(page.getByRole('button', { name: '自动播放', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: /^讨论 10$/ }).click();
  await expect(page.getByTestId('utterance-10')).toBeVisible();
  for (const title of ['讨论结论确认', 'SPEC 基线确认', 'DESIGN 基线确认', 'PLAN 基线确认']) {
    await expect(page.getByTestId('static-gate')).toContainText(title);
    await page.getByRole('button', { name: '批准并推进', exact: true }).click();
  }
  for (let i = 0; i < 3; i++) { await expect(next).toBeEnabled(); await next.click(); }
  await expect(page.locator('[data-id="T-02"]')).toContainText('running');
  await expect(page.locator('[data-id="T-03"]')).toContainText('running');
  await expect(page.locator('[data-id="T-04"]')).toContainText('pending');
  await page.screenshot({ path: test.info().outputPath('classroom-parallel.png'), fullPage: true });
  await page.reload();
  await expect(page.locator('[data-id="T-02"]')).toContainText('running');
  await expect(page.locator('[data-id="T-04"]')).toContainText('pending');
  for (let i = 0; i < 6; i++) { await expect(next).toBeEnabled(); await next.click(); }
  await expect(page.getByTestId('static-acceptance-panel')).toContainText('不计入仓库真实测试统计');
  await page.screenshot({ path: test.info().outputPath('classroom-acceptance.png'), fullPage: true });
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: '重新演示', exact: true }).click();
    await expect(page.getByTestId('static-gate')).toHaveCount(0);
    await expect(next).toBeEnabled();
  }
  expect(apiMock.writes).toEqual([]);
});

test('classroom: autoplay pauses and projector/narrow controls remain reachable', async ({ page, apiMock }) => {
  await page.goto('/workstation/static-classroom');
  await page.getByRole('button', { name: '开始静态演示', exact: true }).click();
  await page.getByRole('button', { name: '自动播放', exact: true }).click();
  await expect(page.getByRole('button', { name: /^讨论 [1-9]/ })).toBeVisible({ timeout: 5000 });
  await page.getByRole('button', { name: '暂停播放', exact: true }).click();
  const readState = () => page.evaluate(() => localStorage.getItem('hexagraph.static-classroom-demo.v1'));
  const paused = await readState();
  // Wait longer than one playback interval to prove pause stops advancement.
  await page.waitForTimeout(1700);
  expect(await readState()).toBe(paused);
  for (const size of [{ width: 1280, height: 720 }, { width: 768, height: 1024 }]) {
    await page.setViewportSize(size);
    const button = page.getByRole('button', { name: '下一步', exact: true });
    await button.scrollIntoViewIfNeeded();
    await expect(button).toBeVisible();
    await button.click();
    await page.screenshot({ path: test.info().outputPath(`classroom-${size.width}.png`), fullPage: true });
  }
  expect(apiMock.writes).toEqual([]);
});
