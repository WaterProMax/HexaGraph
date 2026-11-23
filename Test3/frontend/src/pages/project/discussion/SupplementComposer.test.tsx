import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SupplementComposer } from "./SupplementComposer";

const apiMock = vi.hoisted(() => ({
  supplementDiscussion: vi.fn(),
}));

vi.mock("../../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../api/client")>();
  return { ...actual, api: { ...actual.api, ...apiMock } };
});

const onSent = vi.fn();

function renderComposer() {
  return render(
    <SupplementComposer sessionId="s1" actorBotId="bot-a" onSent={onSent} />,
  );
}

function field(): HTMLTextAreaElement {
  return screen.getByLabelText("补充信息") as HTMLTextAreaElement;
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.supplementDiscussion.mockResolvedValue({ session_id: "s2" });
});

afterEach(cleanup);

describe("SupplementComposer", () => {
  it("sends the trimmed text for the pending session and clears the field", async () => {
    renderComposer();

    fireEvent.change(field(), { target: { value: "  第一版以学生手动上报为准  " } });
    fireEvent.click(screen.getByRole("button", { name: "发送补充" }));

    await waitFor(() =>
      expect(apiMock.supplementDiscussion).toHaveBeenCalledWith(
        "s1",
        "第一版以学生手动上报为准",
        "bot-a",
      ),
    );
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
    expect(field().value).toBe("");
  });

  it("keeps the send button disabled while the field is blank", () => {
    renderComposer();

    const button = screen.getByRole("button", { name: "发送补充" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);

    fireEvent.change(field(), { target: { value: "   " } });
    expect((screen.getByRole("button", { name: "发送补充" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows the error message and keeps the text when the API rejects", async () => {
    apiMock.supplementDiscussion.mockRejectedValue(new Error("只有 Leader 可以补充讨论"));
    renderComposer();

    fireEvent.change(field(), { target: { value: "补充逾期规则" } });
    fireEvent.click(screen.getByRole("button", { name: "发送补充" }));

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("只有 Leader 可以补充讨论"));
    expect(onSent).not.toHaveBeenCalled();
    expect(field().value).toBe("补充逾期规则");
  });

  it("ignores a second submit while the first request is in flight", async () => {
    let resolve: (value: unknown) => void = () => {};
    apiMock.supplementDiscussion.mockImplementation(
      () => new Promise((done) => {
        resolve = done;
      }),
    );
    renderComposer();

    fireEvent.change(field(), { target: { value: "补充逾期规则" } });
    fireEvent.click(screen.getByRole("button", { name: "发送补充" }));
    fireEvent.submit(field().closest("form") as HTMLFormElement);

    expect(apiMock.supplementDiscussion).toHaveBeenCalledTimes(1);
    resolve({ session_id: "s2" });
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
  });
});