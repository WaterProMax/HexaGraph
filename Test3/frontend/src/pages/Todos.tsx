import { List } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export default function Todos() {
  const { id } = useParams();
  const { data } = useQuery({ queryKey: ["todos", id], queryFn: () => api.todos(id!), enabled: !!id });
  return <List dataSource={data || []} renderItem={(i: any) => <List.Item>{i.kind || i.task}</List.Item>} />;
}
