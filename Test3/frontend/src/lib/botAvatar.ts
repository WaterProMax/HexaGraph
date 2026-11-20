/**
 * Deterministic bot avatars, persisted per bot in localStorage.
 *
 * This is a zero-migration front-end preset.  If the backend ever grows
 * `avatar_emoji` / `avatar_color` / `avatar_url` fields on BotInstance, the
 * server copy becomes authoritative and these local presets should be migrated
 * (one-time read of BOT_AVATAR_STORAGE_KEY) rather than kept in parallel.
 * Do not send these fields to BotCreate / BotPatch.
 */

export const BOT_AVATAR_STORAGE_KEY = "hexagraph.botAvatar.v1";

export type BotAvatarPreset = {
  emoji?: string;
  color?: string;
  imageDataUrl?: string;
};

export type AvatarSource = {
  bot_id: string;
  display_name: string;
  role_template: string;
  status?: string;
};

/** Muted, token-adjacent palette; readable with white text. */
export const AVATAR_PALETTE = [
  "#0066fa",
  "#7c3aed",
  "#0f766e",
  "#b45309",
  "#be123c",
  "#475569",
  "#0e7490",
  "#4d7c0f",
];

const HEX_COLOR = /^#[0-9a-f]{6}$/i;

export function hashString(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function defaultAvatarColor(bot: Pick<AvatarSource, "bot_id" | "display_name" | "role_template">): string {
  const seed = `${bot.bot_id}:${bot.role_template}:${bot.display_name}`;
  return AVATAR_PALETTE[hashString(seed) % AVATAR_PALETTE.length];
}

export function defaultInitials(displayName: string): string {
  const name = (displayName || "").trim();
  if (!name) return "?";
  const first = name[0];
  if (/[\u4e00-\u9fff\u3040-\u30ff]/.test(first)) return first;
  const words = name.split(/[\s._-]+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return name.slice(0, 2).toUpperCase();
}

function storageOrNull(storage?: Storage | null): Storage | null {
  if (storage) return storage;
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export function readAvatarPresets(storage?: Storage | null): Record<string, BotAvatarPreset> {
  const target = storageOrNull(storage);
  if (!target) return {};
  try {
    const raw = target.getItem(BOT_AVATAR_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const clean: Record<string, BotAvatarPreset> = {};
    for (const [botId, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!value || typeof value !== "object") continue;
      const record = value as Record<string, unknown>;
      const preset: BotAvatarPreset = {};
      if (typeof record.emoji === "string" && record.emoji.trim()) preset.emoji = record.emoji.trim().slice(0, 4);
      if (typeof record.color === "string" && HEX_COLOR.test(record.color)) preset.color = record.color;
      if (typeof record.imageDataUrl === "string" && record.imageDataUrl.startsWith("data:image/")) {
        preset.imageDataUrl = record.imageDataUrl;
      }
      if (Object.keys(preset).length) clean[botId] = preset;
    }
    return clean;
  } catch {
    return {};
  }
}

export function writeAvatarPreset(
  botId: string,
  preset: BotAvatarPreset,
  storage?: Storage | null,
): Record<string, BotAvatarPreset> {
  const target = storageOrNull(storage);
  const all = readAvatarPresets(target);
  const clean: BotAvatarPreset = {};
  if (preset.emoji && preset.emoji.trim()) clean.emoji = preset.emoji.trim().slice(0, 4);
  if (preset.color && HEX_COLOR.test(preset.color)) clean.color = preset.color;
  if (preset.imageDataUrl && preset.imageDataUrl.startsWith("data:image/")) clean.imageDataUrl = preset.imageDataUrl;
  if (Object.keys(clean).length) all[botId] = clean;
  else delete all[botId];
  try {
    target?.setItem(BOT_AVATAR_STORAGE_KEY, JSON.stringify(all));
  } catch {
    // Storage full or blocked: the in-memory render still uses the default.
  }
  return all;
}

export function clearAvatarPreset(botId: string, storage?: Storage | null): Record<string, BotAvatarPreset> {
  return writeAvatarPreset(botId, {}, storage);
}

export function resolveAvatar(
  bot: AvatarSource,
  presets: Record<string, BotAvatarPreset> = {},
): { label: string; color: string; emoji?: string; imageDataUrl?: string; archived: boolean } {
  const preset = presets[bot.bot_id] || {};
  return {
    label: defaultInitials(bot.display_name),
    color: preset.color || defaultAvatarColor(bot),
    emoji: preset.emoji,
    imageDataUrl: preset.imageDataUrl,
    archived: bot.status === "archived",
  };
}