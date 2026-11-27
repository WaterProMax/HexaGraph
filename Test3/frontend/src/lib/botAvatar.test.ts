import { describe, expect, it } from "vitest";
import {
  BOT_AVATAR_STORAGE_KEY,
  defaultAvatarColor,
  defaultInitials,
  readAvatarPresets,
  resolveAvatar,
  writeAvatarPreset,
  clearAvatarPreset,
} from "./botAvatar";

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (key: string) => map.get(key) ?? null,
    key: (index: number) => Array.from(map.keys())[index] ?? null,
    removeItem: (key: string) => void map.delete(key),
    setItem: (key: string, value: string) => void map.set(key, value),
  };
}

const base = { bot_id: "bot-1", display_name: "Leader A", role_template: "leader" };

describe("deterministic bot avatar", () => {
  it("keeps the same color and initials for the same identity", () => {
    const first = defaultAvatarColor(base);
    const second = defaultAvatarColor({ ...base });
    expect(first).toBe(second);
    expect(defaultInitials("Leader A")).toBe("LA");
    expect(defaultInitials("周明")).toBe("周");
    expect(defaultInitials("")).toBe("?");
  });

  it("changes the color when the name or role changes", () => {
    const variants = [
      defaultAvatarColor(base),
      defaultAvatarColor({ ...base, display_name: "Leader B" }),
      defaultAvatarColor({ ...base, role_template: "coder" }),
    ];
    expect(new Set(variants).size).toBeGreaterThan(1);
  });

  it("persists an emoji and color preset per bot", () => {
    const storage = memoryStorage();
    writeAvatarPreset("bot-1", { emoji: "🦊", color: "#0f766e" }, storage);
    const presets = readAvatarPresets(storage);
    expect(presets["bot-1"]).toEqual({ emoji: "🦊", color: "#0f766e" });
    const resolved = resolveAvatar(base, presets);
    expect(resolved.emoji).toBe("🦊");
    expect(resolved.color).toBe("#0f766e");
    clearAvatarPreset("bot-1", storage);
    expect(readAvatarPresets(storage)).toEqual({});
  });

  it("falls back to defaults when storage is corrupt", () => {
    const storage = memoryStorage();
    storage.setItem(BOT_AVATAR_STORAGE_KEY, "{not-json");
    expect(readAvatarPresets(storage)).toEqual({});
    expect(resolveAvatar(base, {}).label).toBe("LA");
  });

  it("ignores invalid colors and non-image data URLs", () => {
    const storage = memoryStorage();
    storage.setItem(BOT_AVATAR_STORAGE_KEY, JSON.stringify({ "bot-1": { color: "red", imageDataUrl: "javascript:1" } }));
    expect(readAvatarPresets(storage)).toEqual({});
  });

  it("marks archived bots without changing identity", () => {
    const resolved = resolveAvatar({ ...base, status: "archived" }, {});
    expect(resolved.archived).toBe(true);
    expect(resolved.label).toBe("LA");
  });
});