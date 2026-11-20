import { Button, Form, Input } from "antd";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
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
  const projects: any[] = data || [];
  return (
    <div className="page">
      <div className="page-head">
        <h1>项目</h1>
        <p>每个项目可以发起多次运行。新建项目会立即开始阶段 0 的想法解析。</p>
      </div>

      <div className="surface" style={{ padding: 20, marginBottom: 32 }}>
        <Form layout="vertical" requiredMark={false} onFinish={(v) => create.mutate(v)}>
          <Form.Item name="name" label="项目名" rules={[{ required: true, message: "请填写项目名" }]}>
            <Input placeholder="例如：自习室空位查询小程序" />
          </Form.Item>
          <Form.Item name="idea" label="想法" rules={[{ required: true, message: "请描述想法" }]}>
            <Input.TextArea rows={3} placeholder="一两句话的产品想法" />
          </Form.Item>
          <Button htmlType="submit" type="primary" loading={create.isPending}>
            创建并开始
          </Button>
        </Form>
      </div>

      <div className="section-title">
        <span>全部项目</span>
        <span className="hint mono">{projects.length}</span>
      </div>
      {projects.length === 0 ? (
        <div className="well muted" style={{ padding: "14px 16px" }}>
          还没有项目
        </div>
      ) : (
        <div className="grid-list">
          {projects.map((item) => (
            <div className="list-card" key={item.id}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontWeight: 500 }}>{item.name}</div>
                <div className="mono muted">
                  {item.id.slice(0, 8)}
                  {item.profile ? ` · ${item.profile}` : ""}
                </div>
              </div>
              <Link className="chip" to={`/projects/${item.id}`}>
                打开工作台
              </Link>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
