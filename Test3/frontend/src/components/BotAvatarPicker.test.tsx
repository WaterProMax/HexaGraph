import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BOT_AVATAR_STORAGE_KEY, readAvatarPresets } from "../lib/botAvatar";
import { BotAvatarPicker } from "./BotAvatarPicker";

const bot = { bot_id: "bot-1", display_name: "Leader A", role_template: "leader", status: "active" as const };

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("BotAvatarPicker", () => {
  it("writes emoji, color and a reset into localStorage", () => {
    const onChanged = vi.fn();
    render(<BotAvatarPicker bot={bot} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "头像 🦊" }));
    expect(readAvatarPresets()["bot-1"].emoji).toBe("🦊");
    fireEvent.click(screen.getByRole("button", { name: "颜色 #0f766e" }));
    expect(readAvatarPresets()["bot-1"]).toEqual({ emoji: "🦊", color: "#0f766e" });
    fireEvent.click(screen.getByRole("button", { name: "恢复默认头像" }));
    expect(readAvatarPresets()["bot-1"]).toBeUndefined();
    expect(window.localStorage.getItem(BOT_AVATAR_STORAGE_KEY)).toBe("{}");
    expect(onChanged).toHaveBeenCalled();
  });

  it("closes through the close button", () => {
    const onClose = vi.fn();
    render(<BotAvatarPicker bot={bot} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "关闭头像选择器" }));
    expect(onClose).toHaveBeenCalled();
  });
});