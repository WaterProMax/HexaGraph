import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { BotAvatar } from "./BotAvatar";
import { BOT_AVATAR_STORAGE_KEY } from "../lib/botAvatar";

const bot = { bot_id: "bot-1", display_name: "Leader A", role_template: "leader", status: "active" as const };

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("BotAvatar", () => {
  it("renders deterministic initials for the bot", () => {
    render(<BotAvatar bot={bot} />);
    const node = screen.getByTestId("bot-avatar");
    expect(node.getAttribute("data-bot-id")).toBe("bot-1");
    expect(node.textContent).toBe("LA");
    expect(node.getAttribute("aria-label")).toBe("Leader A · leader");
  });

  it("uses the local emoji override", () => {
    window.localStorage.setItem(BOT_AVATAR_STORAGE_KEY, JSON.stringify({ "bot-1": { emoji: "🦊" } }));
    render(<BotAvatar bot={bot} />);
    expect(screen.getByTestId("bot-avatar").textContent).toBe("🦊");
  });

  it("keeps the same test id for archived bots", () => {
    render(<BotAvatar bot={{ ...bot, status: "archived" }} />);
    const node = screen.getByTestId("bot-avatar");
    expect(node.className).toContain("is-archived");
  });
});