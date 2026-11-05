import { Button, Card } from "antd";
import ReactMarkdown from "react-markdown";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export default function Documents() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["arts", id], queryFn: () => api.artifacts(id!), enabled: !!id });
  const { data: run } = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id!), enabled: !!id });
  const gate = (run?.gates || []).find((g: any) => g.status === "pending");
  const resolve = useMutation({
    mutationFn: (decision: string) => api.resolveGate(gate.id, decision, { reason: "confirm" }),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <div>
      {gate && (
        <Card title={`关卡：${gate.kind}`}>
          <Button type="primary" onClick={() => resolve.mutate("approve")}>批准</Button>
          <Button danger onClick={() => resolve.mutate("reject")}>驳回</Button>
        </Card>
      )}
      <Card title="SPEC">
        <ReactMarkdown>{JSON.stringify(data?.spec || {}, null, 2)}</ReactMarkdown>
      </Card>
    </div>
  );
}
