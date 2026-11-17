import { Button, Input, Space, Tag } from "antd";
import { ReactFlow, Background, BackgroundVariant } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { useState } from "react";
import { api, controlEnabled } from "../api/client";
import { readableFlowEdge } from "../flowEdgeStyle";
import { useFlowNodeHover } from "../useFlowNodeHover";

const COLOR: Record<string, string> = {
  pending: "#f5f7f9",
  ready: "#eef5ff",
  running: "#eef8f1",
  verifying: "#ecf8f8",
  done: "#f0f7f2",
  failed: "#fff0f0",
  needs_human: "#fff6ea",
  blocked: "#f4f6f7",
  skipped: "#f6f7f8",
  stale: "#fffbea",
};

export default function Tasks() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["tasks", id], queryFn: () => api.tasks(id!), enabled: !!id });
  const [reason, setReason] = useState("");
  const [selected, setSelected] = useState<any>(null);
  const { hoveredNodeId, hoverNode, leaveNode } = useFlowNodeHover();
  const act = useMutation({
    mutationFn: (action: string) => api.control(selected.code, action, selected.revision, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks", id] }),
  });
  const nodes = (data || []).map((t: any, i: number) => ({
    id: t.code,
    position: { x: 80 + (i % 4) * 180, y: 40 + Math.floor(i / 4) * 100 },
    data: { label: `${t.code} ${t.state}` },
    style: {
      background: COLOR[t.state] || "#fff",
      color: "#304b60",
      border: "1px solid #d4e0e7",
      borderRadius: 8,
      boxShadow: "none",
      padding: "7px 10px",
      fontSize: 12,
    },
  }));
  const edges = (data || []).flatMap((t: any) =>
    (t.card?.depends_on || []).map((d: string) =>
      readableFlowEdge({
        id: `${d}-${t.code}`,
        source: d,
        target: t.code,
        inactive: t.state === "skipped" || t.state === "cancelled",
        focusNodeId: hoveredNodeId || selected?.code,
      }),
    ),
  );
  return (
    <div>
      <div style={{ height: 360 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodeClick={(_, n) => setSelected((data || []).find((t: any) => t.code === n.id))}
          onNodeMouseEnter={(_, n) => hoverNode(n.id)}
          onNodeMouseLeave={(_, n) => leaveNode(n.id)}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={0.7} color="#e3ebf0" />
        </ReactFlow>
      </div>
      {selected && (
        <Space>
          <Tag>{selected.state}</Tag>
          <Input placeholder="理由" value={reason} onChange={(e) => setReason(e.target.value)} />
          {["pause", "resume", "retry", "skip", "force-pass", "takeover", "submit-takeover"].map((a) => (
            <Button key={a} disabled={!controlEnabled(a, selected.state)} onClick={() => act.mutate(a)}>
              {a}
            </Button>
          ))}
          {selected.takeover_workspace && <Tag>接管工作区 {selected.takeover_workspace}</Tag>}
        </Space>
      )}
    </div>
  );
}
