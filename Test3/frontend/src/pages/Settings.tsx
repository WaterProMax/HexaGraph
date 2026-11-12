import { Button } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export default function Settings() {
  const { data } = useQuery({ queryKey: ["models"], queryFn: api.models });
  const test = useMutation({ mutationFn: api.testModels });
  return (
    <div className="page">
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
      <pre className="code-well" style={{ maxHeight: 520 }}>
        {JSON.stringify(data?.slots, null, 2)}
      </pre>
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
