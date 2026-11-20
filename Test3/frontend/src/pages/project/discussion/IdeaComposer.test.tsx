import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../../api/client";
import type { DiscussionSession } from "../../../api/types";
import { IdeaComposer, type IdeaComposerProps } from "./IdeaComposer";

const apiMock = vi.hoisted(() => ({
  createDiscussionSession: vi.fn(),
  runDiscussion: vi.fn(),
}));

vi.mock("../../../api/client", async () => {
  const actual = await vi.importActual<typeof import("../../../api/client")>("../../../api/client");
  return { ...actual, api: apiMock };
});

function session(overrides: Partial<DiscussionSession> = {}): DiscussionSession {
  return { session_id: "sess-1", ...overrides } as DiscussionSession;
}

function makeProps(overrides: Partial<IdeaComposerProps> = {}): IdeaComposerProps {
  return {
    projectId: "p1",
    actorBotId: "bot-a",
    participantBotIds: ["bot-a", "bot-b"],
    memberCount: 2,
    hasLeader: true,
    onInvite: vi.fn(),
    onStarted: vi.fn(),
    ...overrides,
  };
}

function startButton(): HTMLButtonElement {
  return screen.getByRole("button", { name: /开始讨论/ }) as HTMLButtonElement;
}

function typeIdea(value: string) {
  fireEvent.change(screen.getByLabelText("一句话想法"), { target: { value } });
}

beforeEach(() => {
  apiMock.createDiscussionSession.mockReset().mockResolvedValue(session());
  apiMock.runDiscussion.mockReset().mockResolvedValue({ status: "running" });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("IdeaComposer", () => {
  it("disables starting and offers an invite when the team is too small", () => {
    const props = makeProps({ memberCount: 1, hasLeader: false });
    render(<IdeaComposer {...props} />);

    typeIdea("做一个学习室预约页面");
    expect(startButton().disabled).toBe(true);
    expect(screen.getByText(/先邀请 Bot/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "去邀请" }));
    expect(props.onInvite).toHaveBeenCalledTimes(1);
    expect(apiMock.createDiscussionSession).not.toHaveBeenCalled();
  });

  it("disables starting while the idea is blank", () => {
    render(<IdeaComposer {...makeProps()} />);

    expect(startButton().disabled).toBe(true);
    typeIdea("   \n  ");
    expect(startButton().disabled).toBe(true);
    typeIdea("做一个学习室预约页面");
    expect(startButton().disabled).toBe(false);
  });

  it("creates the session, then runs it, then reports the start", async () => {
    const props = makeProps();
    render(<IdeaComposer {...props} />);

    typeIdea("  做一个学习室预约页面  ");
    fireEvent.click(startButton());

    await waitFor(() => expect(props.onStarted).toHaveBeenCalledTimes(1));

    expect(apiMock.createDiscussionSession).toHaveBeenCalledWith(
      "p1",
      {
        leader_bot_id: "bot-a",
        participant_bot_ids: ["bot-a", "bot-b"],
        requirement_snapshot: "做一个学习室预约页面",
      },
      "bot-a",
    );
    expect(apiMock.runDiscussion).toHaveBeenCalledWith("sess-1", "bot-a");
    expect(apiMock.createDiscussionSession.mock.invocationCallOrder[0]).toBeLessThan(
      apiMock.runDiscussion.mock.invocationCallOrder[0],
    );
    expect(props.onStarted).toHaveBeenCalledWith(expect.objectContaining({ session_id: "sess-1" }));
  });

  it("points out secrets, keeps the idea, and re-enables starting", async () => {
    apiMock.createDiscussionSession.mockRejectedValueOnce(
      new ApiError("secret_in_body", { status: 400, category: "secret_in_body" }),
    );
    const props = makeProps();
    render(<IdeaComposer {...props} />);

    const idea = "用 sk-abc123 做一个学习室预约页面";
    typeIdea(idea);
    fireEvent.click(startButton());

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("想法里看起来有密钥，请删除后重试"),
    );
    expect((screen.getByLabelText("一句话想法") as HTMLTextAreaElement).value).toBe(idea);
    expect(startButton().disabled).toBe(false);
    expect(apiMock.runDiscussion).not.toHaveBeenCalled();
    expect(props.onStarted).not.toHaveBeenCalled();
  });

  it("shows the API message when running the discussion fails", async () => {
    apiMock.runDiscussion.mockRejectedValueOnce(new ApiError("模型服务繁忙", { status: 503 }));
    const props = makeProps();
    render(<IdeaComposer {...props} />);

    typeIdea("做一个学习室预约页面");
    fireEvent.click(startButton());

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("模型服务繁忙"));
    expect(startButton().disabled).toBe(false);
    expect(props.onStarted).not.toHaveBeenCalled();
  });

  it("falls back to a generic message for unknown failures", async () => {
    apiMock.createDiscussionSession.mockRejectedValueOnce(new Error(""));
    render(<IdeaComposer {...makeProps()} />);

    typeIdea("做一个学习室预约页面");
    fireEvent.click(startButton());

    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("开始讨论失败，请重试"),
    );
  });

  it("ignores repeated clicks while the request is in flight", async () => {
    let resolveCreate!: (value: DiscussionSession) => void;
    apiMock.createDiscussionSession.mockImplementationOnce(
      () =>
        new Promise<DiscussionSession>((resolve) => {
          resolveCreate = resolve;
        }),
    );
    const props = makeProps();
    render(<IdeaComposer {...props} />);

    typeIdea("做一个学习室预约页面");
    fireEvent.click(startButton());
    fireEvent.click(startButton());

    expect(apiMock.createDiscussionSession).toHaveBeenCalledTimes(1);
    expect(startButton().disabled).toBe(true);

    resolveCreate(session());
    await waitFor(() => expect(props.onStarted).toHaveBeenCalledTimes(1));
    expect(apiMock.runDiscussion).toHaveBeenCalledTimes(1);
  });

  it("clears the previous error when the membership changes", async () => {
    apiMock.createDiscussionSession.mockRejectedValueOnce(new ApiError("boom", { status: 500 }));
    const props = makeProps();
    const { rerender } = render(<IdeaComposer {...props} />);

    typeIdea("做一个学习室预约页面");
    fireEvent.click(startButton());
    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());

    rerender(<IdeaComposer {...props} memberCount={3} participantBotIds={["bot-a", "bot-b", "bot-c"]} />);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
    expect((screen.getByLabelText("一句话想法") as HTMLTextAreaElement).value).toBe("做一个学习室预约页面");
  });
});