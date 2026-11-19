import { Link } from "react-router-dom";

const COPY = {
  "static-classroom": {
    title: "静态课堂演示已下线",
    detail:
      "独立静态课堂演示页面、侧栏入口与预置素材已下线。工作台、项目、模型槽位、设计规格导入、讨论、PLAN 与任务图不受影响。",
  },
  deepseek: {
    title: "DeepSeek 专用入口已下线",
    detail:
      "专用新建入口、按次运行绑定与自动初始化已下线，本页面未发起任何请求。历史 DeepSeek 运行仅支持只读查看，不支持重试、恢复或继续生成 PLAN；通用兼容模型仍可在「模型槽位」配置。",
  },
} as const;

/** Explicit landing page for retired URLs; never restores a run or calls a model. */
export default function RetiredFeature({ feature }: { feature: keyof typeof COPY }) {
  const copy = COPY[feature];
  return (
    <div className="page" data-testid="retired-feature" data-feature={feature}>
      <div className="page-head">
        <h1>{copy.title}</h1>
        <p>{copy.detail}</p>
      </div>
      <div className="surface" style={{ padding: 20, maxWidth: 720 }}>
        <p className="mono muted" style={{ marginTop: 0 }}>
          已下线，只读，不支持继续调用。
        </p>
        <p style={{ marginBottom: 16 }}>
          需要继续工作时，请回到现有工作台：使用通用模型槽位或 scripted / replay 离线设施，新建运行或导入设计规格。
        </p>
        <Link to="/workstation" className="chip">
          返回工作台
        </Link>
      </div>
    </div>
  );
}