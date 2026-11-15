import { test, expect } from './mock-api';

test('creates a project and starts the entered idea', async ({ page, apiMock }) => {
  await page.goto('/workstation');
  await page.getByRole('textbox', { name: '项目名称', exact: true }).fill('自动化离线项目');
  await page.getByRole('textbox', { name: '产品想法', exact: true }).fill('查询自习室空位');
  await page.getByRole('button', { name: /^启动/ }).click();
  await expect(page).toHaveURL(`/workstation/${apiMock.run.id}`);
  await expect(page.getByRole('button', { name: '批准并推进' })).toBeVisible();
  expect(apiMock.writes).toEqual([
    { path: '/projects', body: { name: '自动化离线项目' } },
    { path: '/projects/offline-project-001/runs', body: { idea: '查询自习室空位' } },
  ]);
});

test('approves the pending gate with the entered reason', async ({ page, apiMock }) => {
  apiMock.seed();
  await page.goto(`/workstation/${apiMock.run.id}`);
  await page.getByRole('textbox', { name: '裁决理由' }).fill('已核对需求');
  await page.getByRole('button', { name: '批准并推进' }).click();
  await expect(page.getByRole('button', { name: '批准并推进' })).toHaveCount(0);
  await expect(page.locator('.topbar-right')).toContainText('阶段 1');
  expect(apiMock.writes).toEqual([{ path: '/gates/offline-gate-001/resolve', body: { decision: 'approve', payload: { reason: '已核对需求' } } }]);
});

test('pauses and resumes the active run', async ({ page, apiMock }) => {
  apiMock.seed();
  await page.goto(`/workstation/${apiMock.run.id}`);
  await page.getByRole('button', { name: '暂停', exact: true }).click();
  await expect(page.locator('.topbar-right')).toContainText('已暂停');
  await page.getByRole('button', { name: '恢复', exact: true }).click();
  await expect(page.getByRole('button', { name: '暂停', exact: true })).toBeVisible();
  await expect(page.locator('.topbar-right')).not.toContainText('已暂停');
  expect(apiMock.writes.map(w => w.path)).toEqual([`/runs/${apiMock.run.id}/pause`, `/runs/${apiMock.run.id}/resume`]);
});

test('canceling termination sends no request; confirming sends confirm true', async ({ page, apiMock }) => {
  apiMock.seed();
  await page.goto(`/runs/${apiMock.run.id}`);
  const button = page.getByRole('button', { name: '终止运行', exact: true });
  await expect(button).toBeEnabled();
  const canceled = page.waitForEvent('dialog');
  const clickCancel = button.click();
  const dialog = await canceled;
  expect(dialog.type()).toBe('confirm');
  expect(dialog.message()).toContain('确认终止');
  await dialog.dismiss();
  await clickCancel;
  // A round trip flushes the event handler before checking that cancel had no side effect.
  await expect(button).toBeEnabled();
  expect(apiMock.writes).toEqual([]);
  const confirmed = page.waitForEvent('dialog');
  const clickConfirm = button.click();
  await (await confirmed).accept();
  await clickConfirm;
  await expect(button).toBeDisabled();
  await expect(page.getByText(/状态 terminated/)).toBeVisible();
  expect(apiMock.writes).toEqual([{ path: `/runs/${apiMock.run.id}/terminate`, body: { confirm: true } }]);
});

for (const phase of ['project', 'run'] as const) {
  test(`shows ${phase} creation failure without navigating`, async ({ page, apiMock }) => {
    apiMock.fail(phase === 'project' ? '/projects' : '/projects/offline-project-001/runs');
    await page.goto('/workstation');
    await page.getByRole('button', { name: /^启动/ }).click();
    await expect(page.getByText(/启动失败:.*offline failure/)).toBeVisible();
    await expect(page).toHaveURL('/workstation');
    await expect(page.getByRole('button', { name: /启动/ })).toBeEnabled();
    await expect(page.getByRole('button', { name: /启动/ })).not.toHaveClass(/ant-btn-loading/);
    expect(apiMock.writes).toHaveLength(phase === 'project' ? 1 : 2);
  });
}

test('failed gate approval keeps the gate actionable and shows the error', async ({ page, apiMock }) => {
  apiMock.seed();
  apiMock.fail('/gates/offline-gate-001/resolve');
  await page.goto(`/workstation/${apiMock.run.id}`);
  await page.getByRole('button', { name: '批准并推进' }).click();
  await expect(page.getByText(/关卡处理失败:.*offline failure/)).toBeVisible();
  await expect(page.getByRole('button', { name: '批准并推进' })).toBeEnabled();
  await expect(page.locator('.topbar-right')).toContainText('阶段 0');
  // The same page must recover after the server becomes available, without reload.
  apiMock.fail('');
  await page.getByRole('button', { name: '批准并推进' }).click();
  await expect(page.locator('.topbar-right')).toContainText('阶段 1');
  await expect(page.getByRole('button', { name: '批准并推进' })).toHaveCount(0);
});

test('a 409 gate conflict stays visible and never advances the stage', async ({ page, apiMock }) => {
  apiMock.seed();
  apiMock.fail('/gates/offline-gate-001/resolve', 409);
  await page.goto(`/workstation/${apiMock.run.id}`);
  await page.getByRole('button', { name: '批准并推进' }).click();
  await expect(page.getByText('关卡处理失败: 409', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '批准并推进' })).not.toHaveClass(/ant-btn-loading/);
  await expect(page.locator('.topbar-right')).toContainText('阶段 0');
  expect(apiMock.writes).toEqual([{ path: '/gates/offline-gate-001/resolve', body: { decision: 'approve', payload: {} } }]);
});

test('failed acceptance requires a nonblank reason before approval', async ({ page, apiMock }) => {
  apiMock.seed();
  apiMock.run.gates[0].kind = '验收确认';
  apiMock.run.gates[0].payload = { pass: false };
  await page.goto(`/workstation/${apiMock.run.id}`);
  const approve = page.getByRole('button', { name: '批准并推进' });
  await expect(approve).toBeDisabled();
  await page.getByRole('textbox', { name: '裁决理由' }).fill('   ');
  await expect(approve).toBeDisabled();
  expect(apiMock.writes).toEqual([]);
  await page.getByRole('textbox', { name: '裁决理由' }).fill('  人工核对并接受剩余限制  ');
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect(approve).toHaveCount(0);
  expect(apiMock.writes).toEqual([{ path: '/gates/offline-gate-001/resolve', body: { decision: 'approve', payload: { reason: '人工核对并接受剩余限制' } } }]);
});
