import { Button } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export default function Settings() {
  const { data } = useQuery({ queryKey: ["models"], queryFn: api.models });
  const test = useMutation({ mutationFn: api.testModels });
  const slots: Record<string, any> = (data?.slots as Record<string, any>) || {};

  return (
    <div className="page settings-page">
      <div className="page-head">
        <h1>模型槽位</h1>
        <p>
          槽位与角色定义见 <span className="mono">config/models.yaml</span> 与{" "}
          <span className="mono">config/roles.yaml</span>。
        </p>
      </div>
      <div className="section-title">
        <span>当前配置</span>
        <Button size="small" loading={test.isPending} onClick={() => test.mutate()}>
          测试连通
        </Button>
      </div>
      <div className="settings-slots" data-testid="settings-slots">
        {Object.keys(slots).length === 0 && <div className="well muted">还没有加载到模型槽位。</div>}
        {Object.entries(slots).map(([slot, value]) => (
          <article className="settings-slot" key={slot}>
            <header className="settings-slot-head">
              <span className="settings-slot-name">{slot}</span>
              <span className="mono muted">{String(value?.model ?? "")}</span>
            </header>
            <pre className="code-well settings-slot-json">{JSON.stringify(value, null, 2)}</pre>
          </article>
        ))}
      </div>
      {test.data && (
        <>
          <div className="section-title" style={{ marginTop: 24 }}>
            连通结果
          </div>
          <pre className="code-well">{JSON.stringify(test.data, null, 2)}</pre>
        </>
      )}
    </div>
  );
}