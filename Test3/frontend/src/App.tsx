import { Link, Navigate, NavLink, Route, Routes, useLocation, useParams } from "react-router-dom";
import { AppShell, DEFAULT_NAV_ITEMS } from "./components/AppShell";
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
import RetiredFeature from "./pages/RetiredFeature";
import BotListPage from "./pages/bots/BotListPage";
import ProjectWorkstationPage from "./pages/project/ProjectWorkstationPage";

/** Route table, exported so tests can assert the contract without guessing DOM. */
export const APP_ROUTE_PATHS = [
  "/",
  "/workstation",
  "/workstation/static-classroom",
  "/workstation/:id?",
  "/deepseek/:id?",
  "/projects",
  "/projects/:projectId",
  "/bots",
  "/bots/new",
  "/bots/:id",
  "/settings",
  "/runs/:id/*",
] as const;

export { runDot } from "./components/AppShell";

export default function App() {
  const loc = useLocation();
  return (
    <AppShell navItems={DEFAULT_NAV_ITEMS} currentPath={loc.pathname}>
      <Routes>
        <Route path="/" element={<Navigate to="/workstation" replace />} />
        <Route path="/workstation/static-classroom" element={<RetiredFeature feature="static-classroom" />} />
        <Route path="/deepseek/:id?" element={<RetiredFeature feature="deepseek" />} />
        <Route path="/workstation/:id?" element={<Workstation />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="/projects/:projectId" element={<ProjectWorkstationRoute />} />
        <Route path="/bots" element={<BotListPage />} />
        <Route path="/bots/new" element={<BotListPage mode="create" />} />
        <Route path="/bots/:id" element={<BotListPage mode="edit" />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/runs/:id/*" element={<RunShell />} />
        <Route path="*" element={<Navigate to="/workstation" replace />} />
      </Routes>
    </AppShell>
  );
}

function ProjectWorkstationRoute() {
  const { projectId } = useParams();
  return <ProjectWorkstationPage projectId={projectId || ""} />;
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