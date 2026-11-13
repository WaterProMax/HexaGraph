import { test as base, expect, type Page } from '@playwright/test';

// HTTP boundary only: real React pages, API client and Query cache are exercised.
export async function mockApi(page: Page) {
  const run = { id: 'offline-run-001', project_id: 'offline-project-001', status: 'waiting', stage: '0', revision: 1, paused: false, idea: '离线测试想法', gates: [{ id: 'offline-gate-001', kind: '初步做法确认', status: 'pending', payload: {} }], event_count: 0 };
  const writes: { path: string; body: any }[] = [];
  const unexpected: string[] = [];
  let created = false;
  let fail = '';
  await page.route('**/*', async route => {
    const req = route.request();
    const url = new URL(req.url());
    if (url.origin === 'https://fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '' });
    if (url.origin !== 'http://127.0.0.1:5173') { unexpected.push(req.url()); return route.abort(); }
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const path = url.pathname.slice(4);
    const method = req.method();
    const json = (data: unknown, status = 200) => route.fulfill({ status, json: data });
    if (method === 'POST') {
      writes.push({ path, body: req.postData() ? req.postDataJSON() : null });
      if (path === fail) return json({ detail: 'offline failure' }, 503);
      if (path === '/projects') return json({ id: run.project_id, name: req.postDataJSON().name, profile: 'python-pytest' });
      if (path === `/projects/${run.project_id}/runs`) { created = true; return json({ run, result: {} }); }
      if (path === '/gates/offline-gate-001/resolve') { run.gates[0].status = 'approved'; run.stage = '1'; run.revision++; return json({ ok: true }); }
      if (path === `/runs/${run.id}/pause`) { run.paused = true; return json(run); }
      if (path === `/runs/${run.id}/resume`) { run.paused = false; return json(run); }
      if (path === `/runs/${run.id}/terminate`) { run.status = 'terminated'; return json(run); }
    }
    if (method === 'GET') {
      if (path === '/runs') return json(created ? [run] : []);
      if (path === `/runs/${run.id}`) return json(run);
      if (path === `/runs/${run.id}/artifacts`) return json({});
      if ([`/runs/${run.id}/tasks`, `/runs/${run.id}/todos`, `/runs/${run.id}/events/history`].includes(path)) return json([]);
      if (path === `/runs/${run.id}/budget`) return json({ used: 0, limit: 1500000, per_point: 1500000, warn: false });
      if (path === `/runs/${run.id}/events`) return route.fulfill({ contentType: 'text/event-stream', body: ': ping\n\n' });
    }
    unexpected.push(`${method} ${path}`);
    return json({ detail: 'Unexpected mock route' }, 501);
  });
  return { run, writes, unexpected, seed: () => { created = true; }, fail: (path: string) => { fail = path; } };
}

export const test = base.extend<{ apiMock: Awaited<ReturnType<typeof mockApi>> }>({
  apiMock: [async ({ page }, use) => {
    const errors: string[] = [];
    page.on('pageerror', err => errors.push(err.message));
    const api = await mockApi(page);
    await use(api);
    expect(api.unexpected).toEqual([]);
    expect(errors).toEqual([]);
  }, { auto: true }],
});
export { expect };
