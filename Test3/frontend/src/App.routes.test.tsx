import { useEffect, useState } from "react";
import { MemoryRouter, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

function Probe() {
  const { id } = useParams();
  const nav = useNavigate();
  const [mounts, setMounts] = useState(0);
  useEffect(() => {
    setMounts((n) => n + 1);
  }, []);
  return (
    <div>
      <div data-testid="mounts">{mounts}</div>
      <div data-testid="run-id">{id || "none"}</div>
      <button type="button" onClick={() => nav("/workstation/run-1")}>
        go
      </button>
    </div>
  );
}

describe("workstation route remount", () => {
  it("keeps one Workstation instance when navigating from /workstation to /workstation/:id", () => {
    render(
      <MemoryRouter initialEntries={["/workstation"]}>
        <Routes>
          <Route path="/workstation/:id?" element={<Probe />} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("run-id").textContent).toBe("none");
    fireEvent.click(screen.getByRole("button", { name: "go" }));
    expect(screen.getByTestId("run-id").textContent).toBe("run-1");
    expect(screen.getByTestId("mounts").textContent).toBe("1");
  });
});
