import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

/** 创建项目弹层：只负责新建，成功后直接进入该项目的工作台。 */
export default function Projects() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const close = () => nav("/bots");
  const create = useMutation({
    mutationFn: (projectName: string) => api.createProject(projectName),
    onSuccess: (project) => {
      qc.invalidateQueries({ queryKey: ["projects"] });
      nav(`/projects/${project.id}`);
    },
  });

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") nav("/bots");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [nav]);

  const canCreate = name.trim() !== "" && !create.isPending;
  return (
    <div className="bot-create-overlay" data-testid="project-create-overlay">
      <form
        className="surface bot-create-dialog project-create-dialog"
        data-testid="project-create-form"
        role="dialog"
        aria-modal="true"
        aria-label="创建项目"
        onSubmit={(event) => {
          event.preventDefault();
          if (canCreate)
            create.mutate(name.trim());
        }}
      >
        <button
          type="button"
          className="bot-create-close"
          aria-label="关闭"
          onClick={close}
        >
          ✕
        </button>
        <h2 className="project-create-title">创建项目</h2>
        <label className="project-field">
          <span>项目名</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：自习室空位查询小程序"
          />
        </label>
        {create.isError && <p role="alert">项目创建失败，请重试。</p>}
        <div className="project-create-actions">
          <button type="submit" className="chip primary" disabled={!canCreate}>
            {create.isPending ? "创建中…" : "创建项目"}
          </button>
        </div>
      </form>
    </div>
  );
}
