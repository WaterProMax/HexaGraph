import { useEffect, useMemo, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";
import { FolderOpenOutlined, LeftOutlined } from "@ant-design/icons";
import type { BotInstance } from "../api/types";
import {
  clearAvatarPreset,
  defaultAvatarColor,
  readAvatarPresets,
  writeAvatarPreset,
  type BotAvatarPreset,
} from "../lib/botAvatar";
import { clearProjectIcon, readProjectIcons, writeProjectIcon } from "../lib/projectIcon";
import { BotAvatar } from "./BotAvatar";
import { SIDEBAR_ICON_COLORS, SIDEBAR_ICONS, SidebarGlyph } from "./sidebarIcons";

export type IconEditTarget =
  | { kind: "bot"; bot: Pick<BotInstance, "bot_id" | "display_name" | "role_template" | "status"> }
  | { kind: "project"; project: { id: string; name: string } };

export function SidebarIconPicker({ target, onClose }: { target: IconEditTarget; onClose: () => void }) {
  const botId = target.kind === "bot" ? target.bot.bot_id : "";
  const projectId = target.kind === "project" ? target.project.id : "";
  const initial = target.kind === "bot" ? readAvatarPresets()[botId] : readProjectIcons()[projectId];
  const fallbackColor =
    target.kind === "bot" ? initial?.color || defaultAvatarColor(target.bot) : initial?.color || "#2f80ed";
  const [iconKey, setIconKey] = useState<string | undefined>(initial?.icon);
  const [color, setColor] = useState(fallbackColor);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  const choices = useMemo(() => {
    const term = query.trim().toLowerCase();
    if (!term) return SIDEBAR_ICONS;
    return SIDEBAR_ICONS.filter(
      (choice) => choice.label.toLowerCase().includes(term) || choice.key.includes(term),
    );
  }, [query]);

  const persist = (nextIcon: string | undefined, nextColor: string) => {
    if (target.kind === "bot") {
      const current: BotAvatarPreset = { ...(readAvatarPresets()[botId] || {}), color: nextColor };
      if (nextIcon) {
        current.icon = nextIcon;
        delete current.emoji;
        delete current.imageDataUrl;
      } else {
        delete current.icon;
      }
      writeAvatarPreset(botId, current);
      return;
    }
    writeProjectIcon(projectId, { icon: nextIcon, color: nextColor });
  };

  const chooseIcon = (key: string) => {
    setIconKey(key);
    persist(key, color);
  };

  const chooseColor = (nextColor: string) => {
    setColor(nextColor);
    persist(iconKey, nextColor);
  };

  const reset = () => {
    if (target.kind === "bot") clearAvatarPreset(botId);
    else clearProjectIcon(projectId);
    setIconKey(undefined);
    setColor(target.kind === "bot" ? defaultAvatarColor(target.bot) : "#2f80ed");
  };

  const title = target.kind === "bot" ? target.bot.display_name : target.project.name;
  const backdropClose = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  return createPortal(
    <div className="icon-dialog-mask" onPointerDown={backdropClose}>
      <div
        className="surface icon-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={`编辑图标：${title}`}
        data-testid="sidebar-icon-picker"
      >
        <header className="icon-dialog-head">
          <button type="button" className="icon-dialog-back" aria-label="关闭图标编辑器" onClick={onClose}>
            <LeftOutlined />
          </button>
          <div className="icon-dialog-titles">
            <h2>编辑图标</h2>
            <p>{title}</p>
          </div>
        </header>

        <div className="icon-dialog-preview">
          {target.kind === "bot" ? (
            <BotAvatar bot={target.bot} size={56} nativeTitle={false} preset={{ icon: iconKey, color }} />
          ) : (
            <span className="project-icon-tile" style={{ width: 44, height: 44, background: color }} aria-hidden>
              {iconKey ? <SidebarGlyph name={iconKey} size={25} /> : <FolderOpenOutlined style={{ fontSize: 23 }} />}
            </span>
          )}
          <div className="icon-dialog-preview-text">
            <strong>预览</strong>
          </div>
        </div>

        <input
          className="icon-search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索图标…"
          aria-label="搜索图标"
        />

        <div className="icon-color-row" role="group" aria-label="图标颜色">
          {SIDEBAR_ICON_COLORS.map((swatch) => (
            <button
              key={swatch}
              type="button"
              className={`icon-color-swatch${color === swatch ? " active" : ""}`}
              style={{ background: swatch }}
              aria-label={`颜色 ${swatch}`}
              data-color={swatch}
              onClick={() => chooseColor(swatch)}
            />
          ))}
        </div>

        <div className="icon-grid" role="listbox" aria-label="图标">
          {choices.map((choice) => (
            <button
              key={choice.key}
              type="button"
              role="option"
              aria-selected={iconKey === choice.key}
              aria-label={`图标 ${choice.label}`}
              data-icon={choice.key}
              className={`icon-grid-item${iconKey === choice.key ? " active" : ""}`}
              style={{ color }}
              onClick={() => chooseIcon(choice.key)}
            >
              <choice.Icon style={{ fontSize: 19 }} />
            </button>
          ))}
          {choices.length === 0 && <p className="icon-grid-empty">没有匹配的图标</p>}
        </div>

        <footer className="icon-dialog-foot">
          <button type="button" className="chip" onClick={reset}>
            恢复默认
          </button>
          <button type="button" className="chip primary" onClick={onClose}>
            完成
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}

export default SidebarIconPicker;