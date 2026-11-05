import { Button, Input, Space, Tag } from "antd";
import { ReactFlow, Background } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { useState } from "react";
import { api, controlEnabled } from "../api/client";

const COLOR: Record<string, string> = {
  pending: "#bbb",
  ready: "#1677ff",
  running: "#52c41a",
  verifying: "#13c2c2",
  done: "#237804",
  failed: "#f5222d",
  needs_human: "#fa8c16",
  blocked: "#d9d9d9",
  skipped: "#aaa",
  stale: "#fadb14",
};

export default function Tasks() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["tasks", id], queryFn: () => api.tasks(id!), enabled: !!id });
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const act = useMutation({
    mutationFn: (action: string) => api.control(selected.code, action, selected.revision, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", id] }),
  });
  const nodes = (data || []).map((t: any, i: number) => ({
    id: t.code,
    position: { x: 80 + (i % 4) * 180, y: 40 + Math.floor(i / 4) * 100 },
    data: { label: `${t.code} ${t.state}` },
    style: { background: COLOR[t.state] || "#fff", color: "#000" },
  }));
  const edges = (data || []).flatMap((t: any) =>
    (t.card?.depends_on || []).map((d: string) => ({ id: `${d}-${t.code}`, source: d, target: t.code })),
  );
  return (
    <div>
      <div style={{ height: 360 }}>
        <ReactFlow nodes={nodes} edges={edges} onNodeClick={(_, n) => setSelected((data || []).find((t: any) => t.code === n.id))}>
          <Background />
        </ReactFlow>
      </div>
      {selected && (
        <Space>
          <Tag>{selected.state}</Tag>
          <Input placeholder="理由" value={reason} onChange={(e) => setReason(e.target.value)} />
          {["pause", "resume", "retry", "skip", "force-pass"].map((a) => (
            <Button key={a} disabled={!controlEnabled(a, selected.state)} onClick={() => act.mutate(a)}>
              {a}
            </Button>
          ))}
        </Space>
      )}
    </div>
  );
}
