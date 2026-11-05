import { Card, Progress, Typography } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export default function Overview() {
  const { id } = useParams();
  const { data } = useQuery({ queryKey: ["run", id], queryFn: () => api.run(id!), enabled: !!id });
  const { data: todos } = useQuery({ queryKey: ["todos", id], queryFn: () => api.todos(id!), enabled: !!id });
  const { data: budget } = useQuery({ queryKey: ["budget", id], queryFn: () => api.budget(id!), enabled: !!id });
  const stage = Number(data?.stage || 0);
  return (
    <div>
      <Typography.Title level={4}>运行 {id}</Typography.Title>
      <Progress percent={Math.min(100, (stage / 8) * 100)} />
      <Card title="状态">阶段 {data?.stage} / 状态 {data?.status}</Card>
      <Card title="待办">{todos?.length || 0} 项</Card>
      <Card title="预算">{budget?.used || 0} / {budget?.limit || 0}</Card>
    </div>
  );
}
