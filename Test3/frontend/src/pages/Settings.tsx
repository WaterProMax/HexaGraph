import { Button, Card } from "antd";
import { useMutation, useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export default function Settings() {
  const { data } = useQuery({ queryKey: ["models"], queryFn: api.models });
  const test = useMutation({ mutationFn: api.testModels });
  return (
    <Card title="模型槽位">
      <pre>{JSON.stringify(data?.slots, null, 2)}</pre>
      <Button onClick={() => test.mutate()}>测试连通</Button>
      {test.data && <pre>{JSON.stringify(test.data)}</pre>}
    </Card>
  );
}
