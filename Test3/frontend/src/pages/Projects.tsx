import { Button, Form, Input, List } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function Projects() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const create = useMutation({
    mutationFn: async (values: { name: string; idea: string }) => {
      const p = await api.createProject(values.name);
      return api.createRun(p.id, values.idea);
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      nav(`/workstation/${res.run.id}`);
    },
  });
  return (
    <div>
      <Form layout="vertical" onFinish={(v) => create.mutate(v)}>
        <Form.Item name="name" label="项目名" rules={[{ required: true }]}>
          <Input />
        </Form.Item>
        <Form.Item name="idea" label="想法" rules={[{ required: true }]}>
          <Input.TextArea rows={3} placeholder="一两句话的产品想法" />
        </Form.Item>
        <Button htmlType="submit" type="primary" loading={create.isPending}>
          创建并开始
        </Button>
      </Form>
      <List
        header="项目"
        dataSource={data || []}
        renderItem={(item: any) => <List.Item>{item.name}</List.Item>}
      />
    </div>
  );
}
