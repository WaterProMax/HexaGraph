import type { BotInstance } from "../api/types";
import { readAvatarPresets, resolveAvatar, type BotAvatarPreset } from "../lib/botAvatar";
import { SidebarGlyph } from "./sidebarIcons";

export type BotAvatarProps = {
  bot: Pick<BotInstance, "bot_id" | "display_name" | "role_template" | "status">;
  size?: number;
  title?: string;
  /** Set false when a custom tooltip already labels the avatar. */
  nativeTitle?: boolean;
  className?: string;
  /** Optional override (e.g. an unsaved picker preview). */
  preset?: BotAvatarPreset;
};

export function BotAvatar({ bot, size = 36, title, nativeTitle = true, className = "", preset }: BotAvatarProps) {
  const presets = preset ? { [bot.bot_id]: preset } : readAvatarPresets();
  const resolved = resolveAvatar(bot, presets);
  const label = title || `${bot.display_name} · ${bot.role_template}`;
  const style = {
    width: size,
    height: size,
    minWidth: size,
    background: resolved.imageDataUrl ? "transparent" : resolved.color,
    fontSize: Math.max(11, Math.round(size * 0.4)),
  } as const;

  return (
    <span
      className={`bot-avatar ${resolved.archived ? "is-archived" : ""} ${className}`.trim()}
      style={style}
      data-testid="bot-avatar"
      data-bot-id={bot.bot_id}
      title={nativeTitle ? label : undefined}
      aria-label={label}
      role="img"
    >
      {resolved.imageDataUrl ? (
        <img src={resolved.imageDataUrl} alt="" aria-hidden />
      ) : resolved.icon ? (
        <SidebarGlyph name={resolved.icon} size={Math.round(size * 0.52)} />
      ) : resolved.emoji ? (
        <span aria-hidden>{resolved.emoji}</span>
      ) : (
        <span aria-hidden>{resolved.label}</span>
      )}
    </span>
  );
}

export default BotAvatar;