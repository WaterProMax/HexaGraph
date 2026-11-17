export const STATIC_REQUIREMENT = `做一个“自习室座位查询小程序”：学生可以按校区、楼栋查看自习室，查看可用座位数量和数据更新时间；数据读取失败时看到明确错误提示，并可点击重试。
本轮只做查询，不做座位预约、支付或真实硬件接入。`;

export type DiscussionPhase = "提出方案" | "讨论分歧" | "形成结论";

export interface StaticUtterance {
  seq: number;
  role: "产品" | "架构" | "开发" | "测试";
  speaker: string;
  phase: DiscussionPhase;
  issue?: "D-01" | "D-02";
  body: string;
}

export const STATIC_UTTERANCES: StaticUtterance[] = [
  {
    seq: 1,
    role: "产品",
    speaker: "产品 Agent",
    phase: "提出方案",
    body: "先把期末周最核心的路径做短：学生选择校区和楼栋后，直接看到自习室列表、可用座位数量与开放时间，不在首页堆放管理功能。",
  },
  {
    seq: 2,
    role: "架构",
    speaker: "架构 Agent",
    phase: "提出方案",
    body: "建议用统一的座位快照模型连接页面与数据源：campus、building、room、available_seats、updated_at。查询契约先稳定，后续替换数据源不影响页面。",
  },
  {
    seq: 3,
    role: "开发",
    speaker: "开发 Agent",
    phase: "提出方案",
    body: "实现上拆成查询契约、预置查询服务和座位列表页三部分。服务返回固定示例数据，页面只负责筛选、展示和重试，便于课堂观察前后端并行。",
  },
  {
    seq: 4,
    role: "产品",
    speaker: "产品 Agent",
    phase: "讨论分歧",
    issue: "D-01",
    body: "如果学生看到空位后到场仍被占用，体验会不完整。我提议本轮增加“预约座位”，让查询结果可以直接转成预约。",
  },
  {
    seq: 5,
    role: "架构",
    speaker: "架构 Agent",
    phase: "讨论分歧",
    issue: "D-01",
    body: "预约不是再加一个按钮：它引入学生身份、时段、并发冲突和取消规则，也会改变查询模型。当前案例只有一个查询数据源，无法诚实闭环预约。",
  },
  {
    seq: 6,
    role: "开发",
    speaker: "开发 Agent",
    phase: "形成结论",
    issue: "D-01",
    body: "接受缩小范围：本轮只查询，不预约；支付与真实硬件同样排除。把预约写入暂缓事项，避免后续任务图悄悄扩大工作量。",
  },
  {
    seq: 7,
    role: "开发",
    speaker: "开发 Agent",
    phase: "讨论分歧",
    issue: "D-02",
    body: "首屏可以先突出“实时可用座位数”，用醒目的数字减少信息层级；更新时间放到二级详情，读取失败时显示通用错误即可。",
  },
  {
    seq: 8,
    role: "测试",
    speaker: "测试 Agent",
    phase: "讨论分歧",
    issue: "D-02",
    body: "只写“实时”会掩盖数据陈旧风险。验收必须看到更新时间；失败时不能只显示通用错误，还要保留当前筛选条件并提供可点击的重试入口。",
  },
  {
    seq: 9,
    role: "产品",
    speaker: "产品 Agent",
    phase: "形成结论",
    issue: "D-02",
    body: "采纳测试意见：座位数量与更新时间同级展示，失败文案明确为“座位数据读取失败”，点击重试后重新读取当前校区、楼栋的数据。",
  },
  {
    seq: 10,
    role: "测试",
    speaker: "测试 Agent",
    phase: "形成结论",
    body: "验收固定三类场景：按校区/楼栋筛选结果正确；数量与更新时间完整；失败提示与重试可见。另核对讨论中的预约、支付、硬件排除项没有进入 SPEC 和 PLAN。",
  },
];

export const STATIC_DISCUSSION_CONCLUSION = {
  adopted: [
    "D-01：本轮只提供座位查询，不实现预约。",
    "D-02：同时展示可用座位数量与更新时间，失败时提供明确提示和重试。",
    "统一座位快照契约，页面与预置查询服务可以并行实现。",
  ],
  deferred: ["座位预约与取消", "支付", "真实座位硬件接入"],
  acceptance: [
    "按校区、楼栋筛选自习室，结果与预置数据一致。",
    "每个自习室展示可用座位数量及更新时间。",
    "读取失败出现明确错误提示，重试保留筛选条件。",
  ],
};

export const STATIC_SPEC = {
  code: "SPEC-CLASSROOM-001",
  title: "自习室座位查询小程序 · 需求规格",
  provenance: "人工编写的静态规格，非真实模型生成",
  features: [
    {
      code: "F1",
      title: "按校区与楼栋查询",
      priority: "P0",
      acceptance: "选择校区、楼栋后，只返回匹配的自习室。",
    },
    {
      code: "F2",
      title: "座位数量与更新时间",
      priority: "P0",
      acceptance: "每条结果包含 available_seats 与 updated_at，不宣称实时硬件数据。",
    },
    {
      code: "F3",
      title: "失败提示与重试",
      priority: "P0",
      acceptance: "读取失败显示“座位数据读取失败”，重试保留校区与楼栋筛选。",
    },
  ],
  exclusions: ["座位预约与取消", "支付", "真实硬件接入"],
  traces: { "D-01": ["exclusions"], "D-02": ["F2", "F3"] },
};

export const STATIC_DESIGN = {
  code: "DESIGN-CLASSROOM-001",
  title: "自习室座位查询 · 静态设计规格",
  provenance: "人工编写的静态设计，未执行真实开发",
  modules: [
    { code: "M1", name: "查询契约", responsibility: "定义筛选参数和座位快照字段", sources: ["F1", "F2"] },
    { code: "M2", name: "预置查询服务", responsibility: "返回固定示例与可讲解的失败场景", sources: ["F1", "F3"] },
    { code: "M3", name: "座位列表页面", responsibility: "展示筛选、数量、更新时间、错误与重试", sources: ["F1", "F2", "F3"] },
    { code: "M4", name: "静态场景验收", responsibility: "汇总三个预置验收场景与演示边界", sources: ["F1", "F2", "F3"] },
  ],
  interfaces: [
    {
      code: "C1",
      name: "查询座位快照",
      input: { campus: "string", building: "string" },
      output: {
        room: "string",
        available_seats: "number",
        updated_at: "ISO 8601 string",
      },
      failure: "可读错误信息；页面提供重试，不包含真实网络请求",
    },
  ],
};

export const STATIC_PLAN = {
  code: "PLAN-CLASSROOM-001",
  title: "自习室座位查询 · 静态任务计划",
  capacity: 18,
  provenance: "人工编写的静态任务，未交给真实编排器",
  tasks: [
    {
      code: "T-01",
      title: "确定座位查询接口与数据结构",
      role: "architect",
      kind: "design",
      module: "M1",
      points: 3,
      depends_on: [],
      sources: ["F1", "F2"],
      outputs: ["seat-query-contract.json（预置示例）"],
      write_set: ["demo/contracts"],
      acceptance: [{ cmd: ["预置检查：字段覆盖校区、楼栋、数量和更新时间"] }],
    },
    {
      code: "T-02",
      title: "实现预置座位查询服务",
      role: "backend",
      kind: "impl",
      module: "M2",
      points: 4,
      depends_on: ["T-01"],
      sources: ["F1", "F3"],
      outputs: ["preset-seat-service.ts（预置示例）"],
      write_set: ["demo/service"],
      acceptance: [{ cmd: ["预置检查：筛选、失败与重试场景"] }],
    },
    {
      code: "T-03",
      title: "实现座位列表页面",
      role: "frontend",
      kind: "impl",
      module: "M3",
      points: 4,
      depends_on: ["T-01"],
      sources: ["F1", "F2", "F3"],
      outputs: ["seat-list-page.tsx（预置示例）"],
      write_set: ["demo/ui"],
      acceptance: [{ cmd: ["预置检查：数量、更新时间与重试入口"] }],
    },
    {
      code: "T-04",
      title: "完成前后端联调",
      role: "integrator",
      kind: "integration",
      module: "M2+M3",
      points: 4,
      depends_on: ["T-02", "T-03"],
      sources: ["F1", "F2", "F3"],
      outputs: ["integration-summary.md（预置示例）"],
      write_set: ["demo/integration"],
      acceptance: [{ cmd: ["预置检查：T-02 与 T-03 均完成后才汇合"] }],
    },
    {
      code: "T-05",
      title: "执行场景验收并输出总结",
      role: "qa",
      kind: "acceptance",
      module: "M4",
      points: 3,
      depends_on: ["T-04"],
      sources: ["F1", "F2", "F3"],
      outputs: ["static-acceptance.md（预置示例）"],
      write_set: ["demo/acceptance"],
      acceptance: [{ cmd: ["预置检查：三项场景与演示限制完整"] }],
    },
  ],
};

export const STATIC_TASK_DETAILS: Record<string, { summary: string; artifact: object; presetResult: string }> = {
  "T-01": {
    summary: "固定座位快照契约，作为服务与页面共同依赖。",
    artifact: { campus: "string", building: "string", room: "string", available_seats: "number", updated_at: "string" },
    presetResult: "预置契约检查通过，未执行真实代码。",
  },
  "T-02": {
    summary: "以固定数据模拟校区/楼栋查询和失败重试。",
    artifact: { fixture: "东区 / 求真楼 / 301", available_seats: 12, updated_at: "2026-11-17T09:30:00+08:00" },
    presetResult: "预置服务场景通过，未发起网络请求。",
  },
  "T-03": {
    summary: "以静态页面示例展示筛选、数量、更新时间和重试按钮。",
    artifact: { filters: ["校区", "楼栋"], states: ["success", "error"], retryPreservesFilters: true },
    presetResult: "预置页面场景通过，未执行真实浏览器测试。",
  },
  "T-04": {
    summary: "汇合 T-02 与 T-03 的预置产物，检查字段与状态一致。",
    artifact: { joined: ["T-02", "T-03"], contract: "C1", consistent: true },
    presetResult: "预置联调结论一致，未运行真实前后端。",
  },
  "T-05": {
    summary: "汇总三个静态验收场景，并明确非真实模型或执行证明。",
    artifact: { scenarios: 3, source: "人工编写", execution: "simulated" },
    presetResult: "预置验收材料完整，不计入仓库真实测试统计。",
  },
};

export const STATIC_ACCEPTANCE = {
  title: "静态课堂演示验收总结",
  provenance: "静态课堂演示，非真实模型生成或执行证明",
  scenarios: [
    { code: "A-01", name: "校区与楼栋筛选", result: "预置通过／未真实执行", evidence: "东区 · 求真楼仅返回匹配的自习室" },
    { code: "A-02", name: "数量与更新时间", result: "预置通过／未真实执行", evidence: "301 室显示 12 个可用座位及 2026-11-17 09:30 更新时间" },
    { code: "A-03", name: "失败提示与重试", result: "预置通过／未真实执行", evidence: "显示读取失败说明，重试保留校区与楼栋" },
  ],
  parallelEvidence: "T-02 与 T-03 曾同时处于 running；两者均 done 后 T-04 才进入 ready。",
  limitations: ["所有讨论、任务、产物和结果均为人工编写", "没有调用真实模型或付费 API", "没有真实开发、网络请求、模型日志或业务系统验收"],
};
