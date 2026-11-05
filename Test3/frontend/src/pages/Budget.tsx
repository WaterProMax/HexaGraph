import { Progress } from "antd";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";

export default function Budget() {
  const { id } = useParams();
  const { data } = useQuery({ queryKey: ["budget", id], queryFn: () => api.budget(id!), enabled: !!id });
  const pct = Math.round((data?.ratio || 0) * 100);
  return <Progress percent={pct} status={data?.warn ? "exception" : "active"} />;
}
