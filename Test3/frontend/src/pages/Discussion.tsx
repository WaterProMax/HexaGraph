import { Card, Form, Input, Table, Tag, Button } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

const STATUS: Record<string, string> = { 采纳: "green", 待定: "orange", 撤回: "default", 未讨论: "red" };

export default function Discussion() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["disc", id], queryFn: () => api.discussion(id!), enabled: !!id });
  const { data: run } = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id!), enabled: !!id });
  const gate = (run?.gates || []).find((g: any) => g.status === "pending" && g.kind.includes("争议"));
  const decide = useMutation({
    mutationFn: (v: { code: string; status: string; reason: string }) =>
      api.resolveGate(gate.id, "approve", { verdicts: [v] }),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <div>
      <Card title="第一轮问题">
        <Table rowKey="code" dataSource={data?.questions || []} columns={[{ title: "编号", dataIndex: "code" }, { title: "角色", dataIndex: "role" }, { title: "问题", dataIndex: "text" }]} size="small" />
      </Card>
      <Card title="合并表">
        <Table rowKey="issue" dataSource={data?.merge || []} columns={[{ title: "I", dataIndex: "issue" }, { title: "来自", dataIndex: "from_questions", render: (v) => (v || []).join(",") }, { title: "问题", dataIndex: "text" }]} size="small" />
      </Card>
      <Card title="发言">
        <Table
          rowKey="seq"
          dataSource={data?.utterances || []}
          columns={[
            { title: "#", dataIndex: "seq", width: 56 },
            { title: "角色", dataIndex: "role", width: 100 },
            { title: "规则", dataIndex: "rule", width: 72 },
            { title: "发言", dataIndex: "body" },
          ]}
          size="small"
        />
      </Card>
      <Card title="争议清单">
        <Table
          rowKey="code"
          dataSource={data?.issues || []}
          columns={[
            { title: "编号", dataIndex: "code" },
            { title: "状态", dataIndex: "status", render: (s) => <Tag color={STATUS[s]}>{s}</Tag> },
            { title: "依据", dataIndex: "basis" },
            { title: "去向", dataIndex: "destination", render: (d) => (Array.isArray(d) ? d.join(",") : d) },
            { title: "问题", dataIndex: "text" },
          ]}
          size="small"
        />
        {gate && (
          <Form layout="inline" onFinish={(v) => decide.mutate(v)}>
            <Form.Item name="code" rules={[{ required: true }]}><Input placeholder="I-03" /></Form.Item>
            <Form.Item name="status" rules={[{ required: true }]}><Input placeholder="采纳/撤回" /></Form.Item>
            <Form.Item name="reason" rules={[{ required: true, message: "必须写理由" }]}><Input placeholder="理由" /></Form.Item>
            <Button htmlType="submit">裁决</Button>
          </Form>
        )}
      </Card>
    </div>
  );
}
