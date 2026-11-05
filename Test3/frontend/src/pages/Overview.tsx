import { Button, Card, Progress, Typography } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export default function Overview() {
  const { id } = useParams();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id!), enabled: !!id });
  const { data: todos } = useQuery({ queryKey: ["todos", id], queryFn: () => api.todos(id!), enabled: !!id });
  const { data: budget } = useQuery({ queryKey: ["budget", id], queryFn: () => api.budget(id!), enabled: !!id });
  const terminate = useMutation({
    mutationFn: () => api.terminate(id!),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["run", id] }),
  });
  const stage = Number(data?.stage || 0);
  return (
    <div>
      <Typography.Title level={4}>运行 {id}</Typography.Title>
      <Progress percent={Math.min(100, (stage / 8) * 100)} />
      <Card title="状态">阶段 {data?.stage} / 状态 {data?.status}</Card>
      <Card title="待办">{todos?.length || 0} 项</Card>
      <Card title="预算">{budget?.used || 0} / {budget?.limit || 0}</Card>
      <Button
        danger
        disabled={data?.status === "terminated"}
        onClick={() => {
          if (window.confirm("确认终止这次运行？此操作需二次确认。")) {
            terminate.mutate();
          }
        }}
      >
        终止运行
      </Button>
    </div>
  );
}
