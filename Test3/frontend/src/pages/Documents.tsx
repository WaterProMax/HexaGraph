import { Button, Card, Input } from "antd";
import ReactMarkdown from "react-markdown";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { useState } from "react";
import { api } from "../api/client";

export default function Documents() {
  const { id } = useParams();
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const { data } = useQuery({ queryKey: ["arts", id], queryFn: () => api.artifacts(id!), enabled: !!id });
  const { data: run } = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id!), enabled: !!id });
  const gate = (run?.gates || []).find((g: any) => g.status === "pending");
  const acceptGate = gate?.kind === "验收确认";
  const passed = Boolean(gate?.payload?.pass);
  const resolve = useMutation({
    mutationFn: (decision: string) => api.resolveGate(gate.id, decision, { reason }),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <div>
      {gate && (
        <Card title={`关卡：${gate.kind}`}>
          {acceptGate && !passed && (
            <Input.TextArea
              placeholder="验收未通过，人工确认必须写理由"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              style={{ marginBottom: 8 }}
            />
          )}
          <Button type="primary" disabled={acceptGate && !passed && !reason.trim()} onClick={() => resolve.mutate("approve")}>
            批准
          </Button>
          <Button danger onClick={() => resolve.mutate("reject")}>
            驳回
          </Button>
        </Card>
      )}
      <Card title="SPEC">
        <ReactMarkdown>{JSON.stringify(data?.spec || {}, null, 2)}</ReactMarkdown>
      </Card>
    </div>
  );
}
