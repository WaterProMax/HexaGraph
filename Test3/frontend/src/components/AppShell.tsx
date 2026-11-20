import { useEffect, useState, type ReactNode } from "react";
import {
  AppstoreOutlined,
  DesktopOutlined,
  FolderOpenOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  RobotOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Link, NavLink } from "react-router-dom";
import { api } from "../api/client";
import type { BotInstance } from "../api/types";
import { COMPACT_VIEWPORT } from "../workstationLayout";
import { BotAvatar } from "./BotAvatar";

export type LoadState = "loading" | "empty" | "error" | "forbidden" | "ready";

/** The P6 navigation contract: these keys must always be reachable. */
export const REQUIRED_NAV_KEYS = ["bots", "projects", "settings"] as const;

export type NavItem = { key: string; label: string; to: string };

/** Visible labels stay Chinese where the product already reads that way; keys/hrefs are the contract. */
export const DEFAULT_NAV_ITEMS: NavItem[] = [
  { key: "workstation", label: "工作台", to: "/workstation" },
  { key: "bots", label: "Bot", to: "/bots" },
  { key: "projects", label: "项目", to: "/projects" },
  { key: "settings", label: "模型槽位", to: "/settings" },
];

export type AppShellProps = {
  navItems: Array<{ key: string; label: string; to: string }>;
  currentPath: string;
  children: ReactNode;
};

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

function iconFor(key: string) {
  if (key === "workstation") return <DesktopOutlined />;
  if (key === "bots") return <RobotOutlined />;
  if (key === "projects") return <FolderOpenOutlined />;
  if (key === "settings") return <SettingOutlined />;
  return <AppstoreOutlined />;
}

function isActive(currentPath: string, to: string): boolean {
  if (to === "/") return currentPath === "/";
  return currentPath === to || currentPath.startsWith(`${to}/`);
}

/**
 * Shared application shell: sidebar + recent runs + main column.
 *
 * Extracted from the original inline `Sidebar` so P6 pages can be mounted
 * without a second, unrelated shell.  Collapse-on-narrow-viewport behaviour is
 * preserved.
 */
export function AppShell({ navItems, currentPath, children }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== "undefined" && window.innerWidth < COMPACT_VIEWPORT,
  );
  const { data: runs } = useQuery({ queryKey: ["runs"], queryFn: api.runs, refetchInterval: 3000 });
  const recent = Array.isArray(runs) ? [...runs].reverse().slice(0, 8) : [];
  const {
    data: botList,
    isLoading: botsLoading,
    isError: botsError,
    refetch: refetchBots,
  } = useQuery({ queryKey: ["bots"], queryFn: () => api.bots() });
  const bots: BotInstance[] = Array.isArray(botList?.items) ? botList.items : [];

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(`(max-width: ${COMPACT_VIEWPORT - 1}px)`);
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) setCollapsed(true);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return (
    <div className={`shell ${collapsed ? "sidebar-collapsed" : ""}`}>
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
            onClick={() => setCollapsed((current) => !current)}
          >
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
        </div>
        <div className="sidebar-scroll">
          <nav className="nav-group" aria-label="浏览" id="sidebar-navigation">
            <h2 className="nav-label">浏览</h2>
            {navItems.map((n) => {
              const active = isActive(currentPath, n.to);
              return (
                <Link
                  key={n.key}
                  to={n.to}
                  className={`nav-item ${active ? "active" : ""}`}
                  aria-current={active ? "page" : undefined}
                  aria-label={n.label}
                  title={collapsed ? n.label : undefined}
                >
                  {iconFor(n.key)}
                  <span className="nav-text">{n.label}</span>
                </Link>
              );
            })}
          </nav>
          {collapsed ? (
            <section className="nav-group assistant-rail" aria-labelledby="assistant-rail-heading" data-testid="sidebar-bot-rail">
              <h2 className="nav-label" id="assistant-rail-heading">
                助手
              </h2>
              <Link
                to="/bots/new"
                className="rail-new"
                data-testid="sidebar-new-bot"
                aria-label="新建 Bot"
                title="新建 Bot"
              >
                <PlusOutlined />
              </Link>
              {bots.map((bot) => {
                const label = `${bot.display_name} · ${bot.role_template}`;
                return (
                  <Link
                    key={bot.bot_id}
                    to={`/bots/${bot.bot_id}`}
                    className="rail-avatar"
                    aria-label={label}
                    title={label}
                  >
                    <BotAvatar bot={bot} size={38} title={label} />
                  </Link>
                );
              })}
            </section>
          ) : (
            <section className="nav-group assistant-group" aria-labelledby="assistant-heading" data-testid="sidebar-bot-list">
              <h2 className="nav-label" id="assistant-heading">
                <span>助手</span>
                <span className="mono">{bots.length}</span>
              </h2>
              <Link
                to="/bots/new"
                className="nav-item assistant-new"
                data-testid="sidebar-new-bot"
                aria-label="新建 Bot"
              >
                <PlusOutlined />
                <span className="nav-text">新建 Bot</span>
              </Link>
              {botsLoading && <div className="nav-item muted">加载助手…</div>}
              {botsError && (
                <button type="button" className="nav-item muted assistant-retry" onClick={() => void refetchBots()}>
                  助手加载失败 · 重试
                </button>
              )}
              {!botsLoading && !botsError && bots.length === 0 && (
                <div className="nav-item muted" data-testid="sidebar-bots-empty">
                  还没有 Bot
                </div>
              )}
              {bots.map((bot) => {
                const active = currentPath === `/bots/${bot.bot_id}`;
                return (
                  <Link
                    key={bot.bot_id}
                    to={`/bots/${bot.bot_id}`}
                    className={`nav-item assistant-row ${active ? "active" : ""}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <BotAvatar bot={bot} size={30} />
                    <span className="assistant-text">
                      <span className="assistant-name">{bot.display_name}</span>
                      <span className="assistant-role">{bot.role_template}</span>
                    </span>
                    <span className={`assistant-status status-${bot.status}`}>{bot.status}</span>
                  </Link>
                );
              })}
            </section>
          )}
          <section className="nav-group recent-runs" aria-labelledby="recent-runs-heading">
            <h2 className="nav-label" id="recent-runs-heading">
              <span>最近运行</span>
              <span className="mono">{runs?.length ?? 0}</span>
            </h2>
            {recent.length === 0 && <div className="nav-item muted">暂无运行</div>}
            {recent.map((r: any) => {
              const readOnly = Boolean(r.read_only || r.provenance?.mode === "deepseek");
              return (
                <NavLink
                  key={r.id}
                  to={`/workstation/${r.id}`}
                  className="nav-item"
                  title={readOnly ? "已下线的 DeepSeek 历史运行（只读）" : undefined}
                >
                  <span className={`dot ${runDot(r)}`} />
                  <span className="nav-text">{r.idea || r.id.slice(0, 8)}</span>
                  <span className="nav-meta">{readOnly ? "只读" : `S${r.stage}`}</span>
                </NavLink>
              );
            })}
          </section>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

export default AppShell;