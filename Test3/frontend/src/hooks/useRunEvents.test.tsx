import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useRunEvents } from "./useRunEvents";

const apiEvents = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({ api: { events: apiEvents } }));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  readyState = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  close = vi.fn(() => {
    this.readyState = 2;
  });

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  open() {
    this.onopen?.(new Event("open"));
  }

  fail() {
    this.onerror?.(new Event("error"));
  }

  message(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

describe("useRunEvents recovery", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    apiEvents.mockReset();
    apiEvents.mockResolvedValue([{ seq: 1, kind: "stage.started" }]);
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  it("keeps a disconnect visible, reconnects once, and synchronizes after recovery", async () => {
    const onRecover = vi.fn();
    const { result } = renderHook(() => useRunEvents("run-a", onRecover));
    expect(FakeEventSource.instances).toHaveLength(1);

    act(() => FakeEventSource.instances[0].open());
    await waitFor(() => expect(result.current.connection).toBe("live"));
    expect(onRecover).not.toHaveBeenCalled();

    act(() => FakeEventSource.instances[0].fail());
    expect(result.current.connection).toBe("error");
    expect(result.current.connectionError).toContain("断开");
    expect(FakeEventSource.instances[0].close).toHaveBeenCalledTimes(1);

    act(() => result.current.reconnect());
    expect(FakeEventSource.instances).toHaveLength(2);
    act(() => FakeEventSource.instances[1].open());
    await waitFor(() => expect(onRecover).toHaveBeenCalledTimes(1));
    expect(apiEvents).toHaveBeenLastCalledWith("run-a", 0);
    await waitFor(() => expect(result.current.connection).toBe("live"));
  });

  it("cleans up on run switches and unmount, and ignores the old stream", async () => {
    const { result, rerender, unmount } = renderHook(({ id }) => useRunEvents(id), {
      initialProps: { id: "run-a" },
    });
    const first = FakeEventSource.instances[0];
    act(() => first.open());
    await waitFor(() => expect(result.current.events).toHaveLength(1));

    rerender({ id: "run-b" });
    expect(first.close).toHaveBeenCalled();
    const second = FakeEventSource.instances[1];
    expect(second.url).toContain("run-b");
    act(() => first.message({ seq: 99, kind: "wrong-run" }));
    expect(result.current.events.some((event) => event.kind === "wrong-run")).toBe(false);

    unmount();
    expect(second.close).toHaveBeenCalled();
  });
});
