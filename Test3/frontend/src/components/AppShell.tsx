import { useEffect, useState, type ReactElement, type ReactNode } from "react";
import {
  AppstoreOutlined,
  FolderOpenOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  RobotOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Tooltip } from "antd";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { BotInstance } from "../api/types";
import { BOT_AVATAR_EVENT } from "../lib/botAvatar";
import { roleLabel } from "../lib/botRole";
import { COMPACT_VIEWPORT } from "../workstationLayout";
import { BotAvatar } from "./BotAvatar";

export type LoadState = "loading" | "empty" | "error" | "forbidden" | "ready";

/** Bot and project lists live in their own sidebar sections; extra links are optional. */
export const REQUIRED_NAV_KEYS = [] as const;

export type NavItem = { key: string; label: string; to: string };

export const DEFAULT_NAV_ITEMS: NavItem[] = [];

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
      <path
        d="M12 1.5 21.1 6.75v10.5L12 22.5 2.9 17.25V6.75z"
        fill="url(#hg)"
      />
      <path
        d="M12 7.2 16.2 9.6v4.8L12 16.8l-4.2-2.4V9.6z"
        fill="#fff"
        opacity=".9"
      />
    </svg>
  );
}

function iconFor(key: string) {
  if (key === "bots") return <RobotOutlined />;
  if (key === "projects") return <FolderOpenOutlined />;
  return <AppstoreOutlined />;
}

/** Bot 管理 covers the list and each bot's config page, but not chat or the create dialog. */
function isManagingBots(path: string): boolean {
  if (path === "/bots") return true;
  return (
    path.startsWith("/bots/") && path !== "/bots/new" && !path.endsWith("/chat")
  );
}

function isActive(currentPath: string, to: string): boolean {
  if (to === "/") return currentPath === "/";
  return currentPath === to || currentPath.startsWith(`${to}/`);
}

function SidebarTooltip({ title, description, children }: {
  title: string;
  description: string;
  children: ReactElement;
}) {
  return (
    <Tooltip
      placement="right"
      trigger={["hover", "focus"]}
      color="#fbfdff"
      classNames={{ root: "sidebar-rail-tooltip" }}
      getPopupContainer={(trigger) => trigger.closest<HTMLElement>(".shell") ?? document.body}
      title={<><strong>{title}</strong><span>{description}</span></>}
    >
      {children}
    </Tooltip>
  );
}

/**
 * Shared application shell: sidebar (browse, assistants, projects) + main column.
 *
 * Extracted from the original inline `Sidebar` so P6 pages can be mounted
 * without a second, unrelated shell.  Collapse-on-narrow-viewport behaviour is
 * preserved.
 */
export function AppShell({ navItems, currentPath, children }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(
    () => typeof window !== "undefined" && window.innerWidth < COMPACT_VIEWPORT,
  );
  const [, setAvatarVersion] = useState(0);
  const { data: projectList } = useQuery({
    queryKey: ["projects"],
    queryFn: api.projects,
  });
  const projects: Array<{ id: string; name: string }> = Array.isArray(
    projectList,
  )
    ? projectList
    : [];
  const {
    data: botList,
    isLoading: botsLoading,
    isError: botsError,
    refetch: refetchBots,
  } = useQuery({ queryKey: ["bots"], queryFn: () => api.bots() });
  const bots: BotInstance[] = Array.isArray(botList?.items)
    ? botList.items
    : [];

  useEffect(() => {
    const onAvatarChange = () => setAvatarVersion((value) => value + 1);
    window.addEventListener(BOT_AVATAR_EVENT, onAvatarChange);
    return () => window.removeEventListener(BOT_AVATAR_EVENT, onAvatarChange);
  }, []);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      typeof window.matchMedia !== "function"
    )
      return;
    const query = window.matchMedia(`(max-width: ${COMPACT_VIEWPORT - 1}px)`);
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) setCollapsed(true);
    };
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return (
    <div className={`shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <aside
        className={`sidebar ${collapsed ? "collapsed" : ""}`}
        aria-label="应用导航"
      >
        <div className="sidebar-top">
          <Link
            to="/bots"
            className="brand"
            style={{ color: "inherit", textDecoration: "none" }}
            title={collapsed ? "HexaGraph" : undefined}
            aria-label="HexaGraph"
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
        <div className="sidebar-scroll" role="group" aria-label="导航列表" tabIndex={0}>
          {navItems.length > 0 && (
            <nav
              className="nav-group"
              aria-label="浏览"
              id="sidebar-navigation"
            >
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
          )}
          {collapsed ? (
            <section
              className="nav-group assistant-rail"
              aria-labelledby="assistant-rail-heading"
              data-testid="sidebar-bot-rail"
            >
              <h2 className="nav-label" id="assistant-rail-heading">
                Bot
              </h2>
              {bots.map((bot) => {
                const role = roleLabel(bot.role_template);
                return (
                  <SidebarTooltip key={bot.bot_id} title={bot.display_name} description={role}>
                    <Link to={`/bots/${bot.bot_id}/chat`} className="rail-avatar" aria-label={`${bot.display_name} · ${role}`}>
                      <BotAvatar bot={bot} size={38} nativeTitle={false} />
                    </Link>
                  </SidebarTooltip>
                );
              })}
            </section>
          ) : (
            <section
              className="nav-group assistant-group"
              aria-labelledby="assistant-heading"
              data-testid="sidebar-bot-list"
            >
              <h2 className="nav-label" id="assistant-heading">
                <span>Bot</span>
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
              <Link
                to="/bots"
                className={`nav-item ${isManagingBots(currentPath) ? "active" : ""}`}
                data-testid="sidebar-manage-bots"
                aria-label="Bot 管理"
                aria-current={isManagingBots(currentPath) ? "page" : undefined}
              >
                <SettingOutlined />
                <span className="nav-text">Bot 管理</span>
              </Link>
              {botsLoading && <div className="nav-item muted">加载助手…</div>}
              {botsError && (
                <button
                  type="button"
                  className="nav-item muted assistant-retry"
                  onClick={() => void refetchBots()}
                >
                  助手加载失败 · 重试
                </button>
              )}
              {!botsLoading && !botsError && bots.length === 0 && (
                <div
                  className="nav-item muted"
                  data-testid="sidebar-bots-empty"
                >
                  还没有 Bot
                </div>
              )}
              {bots.map((bot) => {
                const active = currentPath === `/bots/${bot.bot_id}/chat`;
                return (
                  <Link
                    key={bot.bot_id}
                    to={`/bots/${bot.bot_id}/chat`}
                    className={`nav-item assistant-row ${active ? "active" : ""}`}
                    aria-current={active ? "page" : undefined}
                  >
                    <BotAvatar bot={bot} size={30} />
                    <span className="assistant-text">
                      <span className="assistant-name">{bot.display_name}</span>
                      <span className="assistant-role">
                        {bot.role_template}
                      </span>
                    </span>
                    <span className={`assistant-status status-${bot.status}`}>
                      {bot.status}
                    </span>
                  </Link>
                );
              })}
            </section>
          )}
          <section
            className="nav-group project-group"
            aria-labelledby="project-heading"
            data-testid="sidebar-project-list"
          >
            <h2 className="nav-label" id="project-heading">
              <span>项目</span>
              <span className="mono">{projects.length}</span>
            </h2>
            {!collapsed && (
              <Link
                to="/projects/new"
                className="nav-item assistant-new"
                data-testid="sidebar-new-project"
                aria-label="创建项目"
              >
                <PlusOutlined />
                <span className="nav-text">创建项目</span>
              </Link>
            )}
            {projects.map((project) => {
              const active = currentPath === `/projects/${project.id}`;
              const link = (
                <Link
                  key={project.id}
                  to={`/projects/${project.id}`}
                  className={`nav-item${active ? " active" : ""}`}
                  aria-current={active ? "page" : undefined}
                >
                  <FolderOpenOutlined />
                  <span className="nav-text">{project.name}</span>
                </Link>
              );
              return collapsed ? (
                <SidebarTooltip key={project.id} title={project.name} description="项目">{link}</SidebarTooltip>
              ) : link;
            })}
          </section>
        </div>
      </aside>
      <main className="main">{children}</main>
    </div>
  );
}

export default AppShell;
