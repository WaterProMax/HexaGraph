import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { BotInstance } from "../api/types";
import { BotAvatar } from "../components/BotAvatar";

export default function Projects() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const [name, setName] = useState("");
  const [idea, setIdea] = useState("");
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
  const { data: botsData } = useQuery({
    queryKey: ["bots"],
    queryFn: () => api.bots(),
  });
  const bots: BotInstance[] = Array.isArray(botsData?.items)
    ? botsData.items
    : [];
  const [memberMap, setMemberMap] = useState<Record<string, any[]>>({});
  const projectIds = projects.map((project) => project.id).join(",");

  useEffect(() => {
    let cancelled = false;
    if (!projectIds) {
      setMemberMap({});
      return;
    }
    Promise.all(
      projects.map(async (project) => {
        try {
          const res = await api.memberships(String(project.id));
          return [
            String(project.id),
            Array.isArray(res?.items) ? res.items : [],
          ] as const;
        } catch {
          return [String(project.id), []] as const;
        }
      }),
    ).then((entries) => {
      if (!cancelled) setMemberMap(Object.fromEntries(entries));
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectIds]);

  const botById = new Map(bots.map((bot: BotInstance) => [bot.bot_id, bot]));
  const canCreate =
    name.trim() !== "" && idea.trim() !== "" && !create.isPending;
  return (
    <div className="page bot-page project-page" data-testid="projects-page">
      <div className="page-head bot-page-head">
        <h1>项目</h1>
      </div>

      <form
        className="project-create"
        data-testid="project-create-form"
        onSubmit={(event) => {
          event.preventDefault();
          if (canCreate)
            create.mutate({ name: name.trim(), idea: idea.trim() });
        }}
      >
        <label className="project-field">
          <span>项目名</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="例如：自习室空位查询小程序"
          />
        </label>
        <label className="project-field">
          <span>想法</span>
          <textarea
            rows={3}
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            placeholder="一两句话的产品想法"
          />
        </label>
        <button type="submit" className="chip primary" disabled={!canCreate}>
          {create.isPending ? "创建中…" : "创建并开始"}
        </button>
      </form>

      {projects.length > 0 && (
        <div className="grid-list">
          {projects.map((item) => (
            <div className="list-card bot-list-card project-card" key={item.id}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div className="project-card-top">
                  <div style={{ fontWeight: 500 }}>{item.name}</div>
                  <div
                    className="project-member-stack"
                    aria-label={`${item.name} 成员`}
                  >
                    {(memberMap[item.id] || []).length === 0 && (
                      <span className="muted">尚未加入 Bot</span>
                    )}
                    {(memberMap[item.id] || []).map((member: any) => {
                      const bot = botById.get(member.bot_id);
                      return bot ? (
                        <BotAvatar key={member.bot_id} bot={bot} size={22} />
                      ) : null;
                    })}
                    {(() => {
                      const leader = (memberMap[item.id] || []).find(
                        (member: any) => member.is_leader,
                      );
                      const leaderBot = leader
                        ? botById.get(leader.bot_id)
                        : undefined;
                      return leaderBot ? (
                        <span className="hint">
                          Leader · {leaderBot.display_name}
                        </span>
                      ) : null;
                    })()}
                  </div>
                </div>
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
