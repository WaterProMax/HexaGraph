// Mock-API fixtures shared by the flow-layout capture and behaviour scripts (no backend, no model API).
const provenance = {
  mode: 'scripted',
  generation: 'preset',
  generation_label: '预置测试输出（scripted）',
  execution: 'simulated',
  execution_label: '模拟执行（预置工具调用）',
};

function card(code, title, deps, extra = {}) {
  return { code, title, depends_on: deps, role: 'coder', kind: 'impl', module: 'M1', points: 2, ...extra };
}

const dagCards = [
  card('T-01', '搭建项目骨架与配置', []),
  card('T-02', '座位数据模型', ['T-01']),
  card('T-03', '自习室列表接口', ['T-01']),
  card('T-04', '开放时间规则', ['T-01']),
  card('T-05', '实现带有超长名称的座位预约冲突检测与候补队列通知服务（含边界条件与重试）', ['T-01']),
  card('T-06', '鉴权与限流', ['T-01']),
  card('T-07', '空位聚合查询', ['T-02', 'T-03']),
  card('T-08', '时间段过滤', ['T-04']),
  card('T-09', '预约通知', ['T-05', 'T-06']),
  card('T-10', '查询服务集成', ['T-07', 'T-08', 'T-09']),
  card('T-11', '列表页', ['T-10']),
  card('T-12', '详情页', ['T-10']),
  card('T-13', '筛选组件', ['T-10']),
  card('T-14', '收藏功能', ['T-10']),
  card('T-15', '离线缓存', ['T-10']),
  card('T-16', '页面联调', ['T-11', 'T-12']),
  card('T-17', '筛选联调', ['T-13']),
  card('T-18', '缓存与收藏联调', ['T-14', 'T-15']),
  card('T-19', '端到端回归', ['T-16', 'T-17', 'T-18']),
  card('T-20', '发布说明与验收清单', ['T-19', 'T-01'], { kind: 'doc' }),
];
const dagStates = ['done', 'done', 'done', 'done', 'running', 'failed', 'done', 'ready', 'pending', 'pending'];

const modules = [
  { code: 'M1', name: '座位查询', responsibility: '查询与展示实时座位状态', sources: ['F1'] },
  { code: 'M2', name: '开放时间', responsibility: '维护自习室开放时段', sources: ['F2'] },
  { code: 'M3', name: '预约与候补', responsibility: '处理预约冲突与候补队列，并在空位释放时通知候补同学', sources: ['F3'], depends_on: ['M1'] },
  { code: 'M4', name: '通知', responsibility: '站内消息推送', sources: ['F3'] },
  { code: 'M5', name: '管理后台', responsibility: '管理员维护自习室信息', sources: ['F4'] },
];

const designInput = {
  title: '自习室空位查询',
  text: '目标：学生在期末周查看空闲座位。\n功能：查询、筛选、预约。\n',
  source: { kind: 'file', name: 'self-study-room.md' },
  chars: 1834,
  sha256: '9f2c4e1a7b3d5f60812a4c6e8b0d2f4a6c8e0b2d4f6a8c0e2b4d6f8a0c2e4b6d',
};

const spec = {
  features: [
    { code: 'F1', title: '查看空闲座位', priority: 'P0', acceptance: ['列表展示空位数'] },
    { code: 'F2', title: '按开放时间筛选', priority: 'P1', acceptance: ['仅显示开放中'] },
    { code: 'F3', title: '预约与候补', priority: 'P1', acceptance: [] },
    { code: 'F4', title: '管理后台', priority: 'P2', acceptance: [] },
  ],
  nonfunc: [],
};

const scenarios = {
  'layout-dag': {
    run: { id: 'layout-dag', project_id: 'p1', origin: 'design_spec', status: 'running', stage: '7', paused: false, idea: '自习室空位查询', gates: [], provenance },
    artifacts: {
      design_input_status: 'plan_confirmed', design_input: designInput, provenance, spec,
      design: { modules, interfaces: [] }, plan: { tasks: dagCards, capacity: 40 },
      baseline_SPEC: 1, baseline_DESIGN: 1, baseline_PLAN: 1,
    },
    tasks: dagCards.map((c, i) => ({ code: c.code, state: dagStates[i] || 'pending', revision: 1, card: c })),
  },
  'layout-design-gate': {
    run: { id: 'layout-design-gate', project_id: 'p1', origin: 'design_spec', status: 'waiting', stage: '5', paused: false, idea: '自习室空位查询', gates: [{ id: 'g-design', kind: 'DESIGN基线确认', status: 'pending', payload: {} }], provenance },
    artifacts: { design_input_status: 'awaiting_confirmation', design_input: designInput, provenance, spec, design: { modules, interfaces: [{ code: 'C1' }], decisions: [{ code: 'D1', decision: '使用 SQLite' }] } },
    tasks: [],
  },
  'layout-needs-input': {
    run: { id: 'layout-needs-input', project_id: 'p1', origin: 'design_spec', status: 'stopped', stage: '5', paused: false, idea: '自习室空位查询', gates: [], provenance },
    artifacts: {
      design_input_status: 'needs_input', design_input_error_category: 'missing_fields', design_input: designInput, provenance,
      design_input_missing: ['未给出并发上限', '缺少座位状态刷新频率', '未说明预约保留时长', '缺少管理员权限边界', '未定义候补队列长度', '缺少离线场景验收条件'],
    },
    tasks: [],
  },
};

async function mock(page) {
  await page.route(/https:\/\/fonts\.(googleapis|gstatic)\.com\//, (route) => route.fulfill({ contentType: 'text/css', body: '' }));
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    if (!url.pathname.startsWith('/api/')) return route.continue();
    const p = url.pathname.replace(/^\/api/, '');
    const json = (data) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(data) });
    if (p === '/runs') return json(Object.values(scenarios).map((s) => s.run));
    if (p === '/health') return json({ status: 'ok', schedule_mode: 'manual' });
    const m = p.match(/^\/runs\/([^/]+)(\/.*)?$/);
    const s = m && scenarios[m[1]];
    if (!s) return json({});
    const rest = m[2] || '';
    if (rest === '') return json(s.run);
    if (rest === '/artifacts') return json(s.artifacts);
    if (rest === '/tasks') return json(s.tasks);
    if (rest === '/budget') return json({ used: 120000, limit: 1500000 });
    if (rest === '/events') return route.fulfill({ status: 200, contentType: 'text/event-stream', body: ': ping\n\n' });
    if (rest.startsWith('/events/history')) return json([]);
    return json({});
  });
}

module.exports = { scenarios, mock, dagCards };
