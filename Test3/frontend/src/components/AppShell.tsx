import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactElement, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import {
  AppstoreOutlined,
  EditOutlined,
  FolderOpenOutlined,
  InboxOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  PlusOutlined,
  RobotOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { message, Tooltip } from "antd";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { BotInstance } from "../api/types";
import { BOT_AVATAR_EVENT } from "../lib/botAvatar";
import { roleLabel } from "../lib/botRole";
import { COMPACT_VIEWPORT } from "../workstationLayout";
import { BotAvatar } from "./BotAvatar";
import { ProjectIcon } from "./ProjectIcon";
import { SidebarIconPicker, type IconEditTarget } from "./SidebarIconPicker";

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
        <linearGradient id="hg" x1="3" y1="2" x2="21" y2="22" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#28a8ff" />
          <stop offset="1" stopColor="#0054e6" />
        </linearGradient>
      </defs>
      <path
        d="M4 2.2 4 20.6l5.5-5.3 3.2 6.9 3.6-1.7-3.2-6.8h6.9z"
        fill="url(#hg)"
        stroke="rgba(0, 58, 158, 0.32)"
        strokeWidth="0.7"
        strokeLinejoin="round"
      />
      <path d="M4 2.2 4 20.6l5.5-5.3-1.2-2.7z" fill="#ffffff" opacity=".22" />
      <path d="M9.5 15.3 12.7 22.2l3.6-1.7-3.2-6.8z" fill="#00358c" opacity=".16" />
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

type ProjectItem = { id: string; name: string; archived?: boolean };

type SidebarMenuTarget =
  | { kind: "project"; project: ProjectItem }
  | { kind: "bot"; bot: BotInstance };

type SidebarMenuState = { x: number; y: number; target: SidebarMenuTarget };

function SidebarContextMenu({
  state,
  onEditIcon,
  onArchiveProject,
  onArchiveBot,
  onClose,
}: {
  state: SidebarMenuState;
  onEditIcon: (target: SidebarMenuTarget) => void;
  onArchiveProject: (project: ProjectItem) => void;
  onArchiveBot: (bot: BotInstance) => void;
  onClose: () => void;
}) {
  const { target } = state;
  const name = target.kind === "project" ? target.project.name : target.bot.display_name;
  return createPortal(
    <div
      className="project-context-menu"
      role="menu"
      aria-label={`${name} 操作`}
      style={{ left: state.x, top: state.y }}
      onPointerDown={(event) => event.stopPropagation()}
      onContextMenu={(event) => event.preventDefault()}
    >
      <div className="project-context-title">{name}</div>
      <button
        type="button"
        role="menuitem"
        className="project-context-item"
        onClick={() => {
          onEditIcon(target);
          onClose();
        }}
      >
        <EditOutlined />
        <span>编辑图标</span>
      </button>
      {target.kind === "bot" ? (
        <button
          type="button"
          role="menuitem"
          className="project-context-item danger"
          onClick={() => {
            onArchiveBot(target.bot);
            onClose();
          }}
        >
          <InboxOutlined />
          <span>归档 Bot</span>
        </button>
      ) : (
        <button
          type="button"
          role="menuitem"
          className="project-context-item danger"
          onClick={() => {
            onArchiveProject(target.project);
            onClose();
          }}
        >
          <InboxOutlined />
          <span>归档项目</span>
        </button>
      )}
    </div>,
    document.body,
  );
}

function ArchiveBotDialog({
  bot,
  pending,
  onCancel,
  onConfirm,
}: {
  bot: BotInstance;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return createPortal(
    <div
      className="icon-dialog-mask"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget && !pending) onCancel();
      }}
    >
      <div className="surface icon-dialog archive-confirm-dialog" role="alertdialog" aria-modal="true">
        <h2>归档「{bot.display_name}」？</h2>
        <p className="muted">
          归档后该 Bot 不再参与新运行，已配置的 API Key 会被清除；历史记录保留。
        </p>
        <div className="archive-confirm-actions">
          <button type="button" className="chip" onClick={onCancel} disabled={pending}>
            取消
          </button>
          <button type="button" className="chip danger" onClick={onConfirm} disabled={pending}>
            {pending ? "归档中…" : "确认归档"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

type PillRect = { left: number; top: number; width: number; height: number };

/**
 * Slides a glass capsule from the previously active sidebar item to the new one.
 * The resting capsule is drawn by the active item's ::before; the ghost only
 * exists in flight so it can pass over other nav groups' glass panes.
 */
function useSidebarActivePill(
  scrollRef: RefObject<HTMLDivElement | null>,
  ghostRef: RefObject<HTMLSpanElement | null>,
  deps: unknown[],
) {
  const lastRect = useRef<PillRect | null>(null);
  const lastCollapsed = useRef<boolean | null>(null);
  const flight = useRef<{ el: HTMLElement; anim: Animation } | null>(null);

  useLayoutEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const collapsedNow = root.closest(".sidebar")?.classList.contains("collapsed") ?? false;
    if (lastCollapsed.current !== null && lastCollapsed.current !== collapsedNow) {
      lastRect.current = null;
    }
    lastCollapsed.current = collapsedNow;

    const endFlight = () => {
      const current = flight.current;
      if (!current) return;
      current.anim.cancel();
      current.el.classList.remove("pill-flight");
      if (ghostRef.current) ghostRef.current.style.opacity = "0";
      flight.current = null;
    };

    const measure = (animate: boolean) => {
      const active = root.querySelector<HTMLElement>(".nav-item.active, .rail-avatar.active");
      if (!active) {
        lastRect.current = null;
        return;
      }
      const rootBox = root.getBoundingClientRect();
      const box = active.getBoundingClientRect();
      const next: PillRect = {
        left: box.left - rootBox.left + root.scrollLeft,
        top: box.top - rootBox.top + root.scrollTop,
        width: box.width,
        height: box.height,
      };
      const prev = lastRect.current;
      lastRect.current = next;
      if (!animate || !prev) return;
      if (
        Math.abs(prev.left - next.left) < 1 &&
        Math.abs(prev.top - next.top) < 1 &&
        Math.abs(prev.width - next.width) < 1 &&
        Math.abs(prev.height - next.height) < 1
      ) {
        return;
      }
      const ghost = ghostRef.current;
      if (!ghost || typeof ghost.animate !== "function") return;
      endFlight();
      Object.assign(ghost.style, {
        left: `${next.left}px`,
        top: `${next.top}px`,
        width: `${next.width}px`,
        height: `${next.height}px`,
        opacity: "1",
      });
      active.classList.add("pill-flight");
      const dx = prev.left - next.left;
      const dy = prev.top - next.top;
      const vertical = Math.abs(dy) >= Math.abs(dx);
      const anim = ghost.animate(
        [
          { transform: `translate(${dx}px, ${dy}px) scale(${vertical ? 1 : 1.1}, ${vertical ? 1.12 : 1})`, opacity: 1 },
          { transform: `translate(${dx * 0.4}px, ${dy * 0.4}px) scale(${vertical ? 1.05 : 1.05}, ${vertical ? 1.06 : 1.05})`, opacity: 0.7, offset: 0.4 },
          { transform: `translate(0px, 0px) scale(${vertical ? 1.03 : 1.02}, ${vertical ? 1.02 : 1.03})`, opacity: 0.15, offset: 0.65 },
          { transform: "translate(0px, 0px) scale(1.01, 1.01)", opacity: 0, offset: 0.85 },
          { transform: "translate(0px, 0px) scale(1, 1)", opacity: 0, offset: 1 },
        ],
        { duration: 520, easing: "cubic-bezier(.32,.72,.32,1)" },
      );
      let fallback = 0;
      let reveal = 0;
      const finish = () => {
        if (fallback) window.clearTimeout(fallback);
        if (reveal) window.clearTimeout(reveal);
        if (ghostRef.current) ghostRef.current.style.opacity = "0";
        active.classList.remove("pill-flight");
        if (flight.current?.anim === anim) flight.current = null;
      };
      // Cross-fade to the resting pill before the ghost lands so the target never sits under a white veil.
      reveal = window.setTimeout(() => active.classList.remove("pill-flight"), 340);
      anim.onfinish = finish;
      anim.oncancel = finish;
      fallback = window.setTimeout(finish, 900);
      flight.current = { el: active, anim };
    };

    measure(true);
    const settle = window.setTimeout(() => measure(false), 260);
    const onResize = () => {
      lastRect.current = null;
      measure(false);
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.clearTimeout(settle);
      window.removeEventListener("resize", onResize);
      endFlight();
    };
  }, deps);
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
  const [sidebarMenu, setSidebarMenu] = useState<SidebarMenuState | null>(null);
  const [iconTarget, setIconTarget] = useState<IconEditTarget | null>(null);
  const [botToArchive, setBotToArchive] = useState<BotInstance | null>(null);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: projectList } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.projects(true),
  });
  const allProjects: ProjectItem[] = Array.isArray(projectList)
    ? projectList
    : [];
  const projects = allProjects.filter((project) => !project.archived);
  const restoreProject = useMutation({
    mutationFn: (project: ProjectItem) => api.restoreProject(project.id),
    onSuccess: (_data, project) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      message.success(`已恢复「${project.name}」`);
    },
    onError: () => message.error("恢复失败，请重试"),
  });
  const archiveProject = useMutation({
    mutationFn: (project: ProjectItem) => api.archiveProject(project.id),
    onSuccess: (_data, project) => {
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
      if (currentPath === `/projects/${project.id}`) navigate("/bots");
      message.success({
        content: (
          <span className="archive-toast">
            已归档「{project.name}」
            <button
              type="button"
              className="archive-toast-undo"
              onClick={() => restoreProject.mutate(project)}
            >
              撤销
            </button>
          </span>
        ),
        duration: 6,
      });
    },
    onError: () => message.error("归档失败，请重试"),
  });
  const {
    data: botList,
    isLoading: botsLoading,
    isError: botsError,
    refetch: refetchBots,
  } = useQuery({ queryKey: ["bots"], queryFn: () => api.bots() });
  const bots: BotInstance[] = Array.isArray(botList?.items)
    ? botList.items
    : [];
  const sidebarBots = bots.filter((bot) => bot.status !== "archived");
  const archiveBot = useMutation({
    mutationFn: (bot: BotInstance) => api.archiveBot(bot.bot_id),
    onSuccess: (_data, bot) => {
      void queryClient.invalidateQueries({ queryKey: ["bots"] });
      setBotToArchive(null);
      if (currentPath.startsWith(`/bots/${bot.bot_id}`)) navigate("/bots");
      message.success(`已归档「${bot.display_name}」`);
    },
    onError: () => message.error("归档失败，请重试"),
  });
  const sidebarScrollRef = useRef<HTMLDivElement | null>(null);
  const activePillGhostRef = useRef<HTMLSpanElement | null>(null);
  useSidebarActivePill(sidebarScrollRef, activePillGhostRef, [
    currentPath,
    collapsed,
    sidebarBots.length,
    projects.length,
  ]);

  useEffect(() => {
    const onAvatarChange = () => setAvatarVersion((value) => value + 1);
    window.addEventListener(BOT_AVATAR_EVENT, onAvatarChange);
    return () => window.removeEventListener(BOT_AVATAR_EVENT, onAvatarChange);
  }, []);

  useEffect(() => {
    if (!sidebarMenu) return;
    const close = () => setSidebarMenu(null);
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [sidebarMenu]);

  const openSidebarMenu = (event: ReactMouseEvent, target: SidebarMenuTarget) => {
    event.preventDefault();
    event.stopPropagation();
    const menuWidth = 184;
    const menuHeight = 124;
    setSidebarMenu({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - menuWidth - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - menuHeight - 8)),
      target,
    });
  };

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
        <div className="sidebar-scroll" ref={sidebarScrollRef} role="group" aria-label="导航列表" tabIndex={0}>
          <span className="sidebar-active-ghost" ref={activePillGhostRef} aria-hidden="true" />
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
              {sidebarBots.map((bot) => {
                const role = roleLabel(bot.role_template);
                const active = currentPath.startsWith(`/bots/${bot.bot_id}`);
                return (
                  <SidebarTooltip key={bot.bot_id} title={bot.display_name} description={role}>
                    <Link
                      to={`/bots/${bot.bot_id}/chat`}
                      className={`rail-avatar${active ? " active" : ""}`}
                      aria-current={active ? "page" : undefined}
                      aria-label={`${bot.display_name} · ${role}`}
                      onContextMenu={(event) => openSidebarMenu(event, { kind: "bot", bot })}
                    >
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
                <span className="mono">{sidebarBots.length}</span>
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
              {sidebarBots.map((bot) => {
                const active = currentPath === `/bots/${bot.bot_id}/chat`;
                return (
                  <Link
                    key={bot.bot_id}
                    to={`/bots/${bot.bot_id}/chat`}
                    className={`nav-item assistant-row ${active ? "active" : ""}`}
                    aria-current={active ? "page" : undefined}
                    onContextMenu={(event) => openSidebarMenu(event, { kind: "bot", bot })}
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
                  onContextMenu={(event) => openSidebarMenu(event, { kind: "project", project })}
                >
                  <ProjectIcon projectId={project.id} />
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
      {sidebarMenu && (
        <SidebarContextMenu
          state={sidebarMenu}
          onEditIcon={(target) =>
            setIconTarget(
              target.kind === "bot"
                ? { kind: "bot", bot: target.bot }
                : { kind: "project", project: { id: target.project.id, name: target.project.name } },
            )
          }
          onArchiveProject={(project) => archiveProject.mutate(project)}
          onArchiveBot={(bot) => setBotToArchive(bot)}
          onClose={() => setSidebarMenu(null)}
        />
      )}
      {iconTarget && <SidebarIconPicker target={iconTarget} onClose={() => setIconTarget(null)} />}
      {botToArchive && (
        <ArchiveBotDialog
          bot={botToArchive}
          pending={archiveBot.isPending}
          onCancel={() => setBotToArchive(null)}
          onConfirm={() => archiveBot.mutate(botToArchive)}
        />
      )}
    </div>
  );
}

export default AppShell;
