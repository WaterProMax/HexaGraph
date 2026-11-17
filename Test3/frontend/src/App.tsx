import { ApiOutlined, DesktopOutlined, FolderOpenOutlined, MenuFoldOutlined, MenuUnfoldOutlined, PlayCircleOutlined, SettingOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useParams } from "react-router-dom";
import { api } from "./api/client";
import Overview from "./pages/Overview";
import Projects from "./pages/Projects";
import Discussion from "./pages/Discussion";
import Documents from "./pages/Documents";
import Todos from "./pages/Todos";
import Tasks from "./pages/Tasks";
import Timeline from "./pages/Timeline";
import Budget from "./pages/Budget";
import Settings from "./pages/Settings";
import Changes from "./pages/Changes";
import Workstation from "./pages/Workstation";
import StaticClassroomDemo from "./pages/StaticClassroomDemo";

export function runDot(run: any): string {
  if (run?.status === "done") return "completed";
  if (run?.status === "waiting" || run?.paused) return "error";
  if (run?.status === "running") return "in_progress";
  return "pending";
}

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 24 24" aria-hidden>
      <defs>
        <linearGradient id="hg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#0bf" />
          <stop offset="1" stopColor="#0066fa" />
        </linearGradient>
      </defs>
      <path d="M12 1.5 21.1 6.75v10.5L12 22.5 2.9 17.25V6.75z" fill="url(#hg)" />
      <path d="M12 7.2 16.2 9.6v4.8L12 16.8l-4.2-2.4V9.6z" fill="#fff" opacity=".9" />
    </svg>
  );
}

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const loc = useLocation();
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 3000 });
  const recent = Array.isArray(runs) ? [...runs].reverse().slice(0, 8) : [];

  const nav = [
    { to: "/workstation/static-classroom", icon: <PlayCircleOutlined />, label: "静态课堂演示", match: "/workstation/static-classroom" },
    { to: "/workstation", icon: <DesktopOutlined />, label: "工作台", match: "/workstation" },
    { to: "/deepseek", icon: <ApiOutlined />, label: "DeepSeek", match: "/deepseek" },
    { to: "/projects", icon: <FolderOpenOutlined />, label: "项目", match: "/projects" },
    { to: "/settings", icon: <SettingOutlined />, label: "模型槽位", match: "/settings" },
  ];

  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`} aria-label="应用导航">
      <div className="sidebar-top">
        <Link
          to="/workstation"
          className="brand"
          style={{ color: "inherit", textDecoration: "none" }}
          title={collapsed ? "HexaGraph" : undefined}
          aria-label="HexaGraph 工作台"
        >
          <BrandMark />
          <span className="brand-name">HexaGraph</span>
        </Link>
        <button
          type="button"
          className="sidebar-toggle"
          aria-label={collapsed ? "展开导航" : "收起导航"}
          aria-expanded={!collapsed}
          title={collapsed ? "展开导航" : "收起导航"}
          onClick={onToggle}
        >
          {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
        </button>
      </div>
      <div className="sidebar-scroll">
        <nav className="nav-group" aria-label="浏览" id="sidebar-navigation">
          <h2 className="nav-label">浏览</h2>
          {nav.map((n) => {
            const active =
              loc.pathname.startsWith(n.match) &&
              (n.to !== "/workstation" || !loc.pathname.startsWith("/workstation/static-classroom"));
            return (
              <Link
                key={n.to}
                to={n.to}
                className={`nav-item ${active ? "active" : ""}`}
                aria-current={active ? "page" : undefined}
                aria-label={n.label}
                title={collapsed ? n.label : undefined}
              >
                {n.icon}
                <span className="nav-text">{n.label}</span>
              </Link>
            );
          })}
        </nav>
        <section className="nav-group recent-runs" aria-labelledby="recent-runs-heading">
          <h2 className="nav-label" id="recent-runs-heading">
            <span>最近运行</span>
            <span className="mono">{runs?.length ?? 0}</span>
          </h2>
          {recent.length === 0 && <div className="nav-item muted">暂无运行</div>}
          {recent.map((r: any) => (
            <NavLink
              key={r.id}
              to={`${r.provenance?.mode === "deepseek" ? "/deepseek" : "/workstation"}/${r.id}`}
              className="nav-item"
            >
              <span className={`dot ${runDot(r)}`} />
              <span className="nav-text">{r.idea || r.id.slice(0, 8)}</span>
              <span className="nav-meta">S{r.stage}</span>
            </NavLink>
          ))}
        </section>
      </div>
    </aside>
  );
}

export default function App() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className={`shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}>
      <Sidebar collapsed={sidebarCollapsed} onToggle={() => setSidebarCollapsed((current) => !current)} />
      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/workstation" replace />} />
          <Route path="/workstation/static-classroom" element={<StaticClassroomDemo />} />
          <Route path="/deepseek/:id?" element={<Workstation deepSeekOnly />} />
          <Route path="/workstation/:id?" element={<Workstation />} />
          <Route path="/projects" element={<Projects />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/runs/:id/*" element={<RunShell />} />
          <Route path="*" element={<Navigate to="/workstation" replace />} />
        </Routes>
      </main>
    </div>
  );
}

function RunShell() {
  const { id } = useParams();
  const tabs = [
    { to: `/runs/${id}`, label: "总览", end: true },
    { to: `/runs/${id}/discussion`, label: "讨论" },
    { to: `/runs/${id}/docs`, label: "文档" },
    { to: `/runs/${id}/todos`, label: "待办" },
    { to: `/runs/${id}/tasks`, label: "任务图" },
    { to: `/runs/${id}/timeline`, label: "时间线" },
    { to: `/runs/${id}/budget`, label: "预算" },
    { to: `/runs/${id}/changes`, label: "变更与反馈" },
  ];
  return (
    <div className="page">
      <div className="page-head">
        <h1>运行详情</h1>
        <p className="mono">{id}</p>
      </div>
      <div className="subnav">
        <Link to={`/workstation/${id}`} className="chip">
          ← 工作台视图
        </Link>
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `chip ${isActive ? "active" : ""}`}>
            {t.label}
          </NavLink>
        ))}
      </div>
      <Routes>
        <Route index element={<Overview />} />
        <Route path="discussion" element={<Discussion />} />
        <Route path="docs" element={<Documents />} />
        <Route path="todos" element={<Todos />} />
        <Route path="tasks" element={<Tasks />} />
        <Route path="timeline" element={<Timeline />} />
        <Route path="budget" element={<Budget />} />
        <Route path="changes" element={<Changes />} />
      </Routes>
    </div>
  );
}
