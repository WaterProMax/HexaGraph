"""Small runnable deliverables for the explicitly selected discussion demo."""

TASK_FILES = {
    "T1": ("seat_service.py", '''from datetime import datetime, timedelta, timezone


class SeatService:
    def __init__(self):
        self.rows = {}
        self.last_reports = {}

    def report(self, user, floor, seats, now=None):
        now = now or datetime.now(timezone.utc)
        if not floor or not isinstance(seats, int) or isinstance(seats, bool) or seats < 0:
            raise ValueError("invalid report")
        previous = self.last_reports.get(user)
        if previous is not None and now - previous < timedelta(minutes=10):
            raise ValueError("report rate limit")
        self.last_reports[user] = now
        self.rows[floor] = {"floor": floor, "seats": seats, "updated_at": now}
        return self.query(now)

    def query(self, now=None):
        now = now or datetime.now(timezone.utc)
        return [dict(row, expired=now - row["updated_at"] > timedelta(minutes=30),
                     available=row["seats"] if now - row["updated_at"] <= timedelta(minutes=30) else 0)
                for _, row in sorted(self.rows.items())]
'''),
    "T2": ("tests/test_seats.py", '''from datetime import datetime, timedelta, timezone
import pytest
from seat_service import SeatService


def test_query_and_report():
    service = SeatService()
    assert service.query() == []
    result = service.report("student", "2F", 12)
    assert result[0]["available"] == 12
    assert not result[0]["expired"]


def test_rate_limit():
    service = SeatService()
    now = datetime.now(timezone.utc)
    service.report("student", "2F", 12, now)
    with pytest.raises(ValueError, match="rate limit"):
        service.report("student", "2F", 10, now + timedelta(minutes=9))
    assert service.report("student", "2F", 10, now + timedelta(minutes=10))[0]["seats"] == 10


def test_expiry():
    service = SeatService()
    now = datetime.now(timezone.utc)
    service.report("student", "2F", 12, now)
    assert service.query(now + timedelta(minutes=30))[0]["available"] == 12
    expired = service.query(now + timedelta(minutes=31))[0]
    assert expired["expired"] and expired["available"] == 0


@pytest.mark.parametrize("seats", [-1, "10", True])
def test_invalid_report(seats):
    with pytest.raises(ValueError):
        SeatService().report("student", "2F", seats)
'''),
    "T3": ("api.py", '''from seat_service import SeatService

service = SeatService()


def query_seats():
    return {"ok": True, "data": service.query()}


def report_seats(user, floor, seats):
    try:
        return {"ok": True, "data": service.report(user, floor, seats)}
    except ValueError as error:
        return {"ok": False, "error": str(error)}
'''),
    "T4": ("frontend/src/App.tsx", '''import { useEffect, useState } from "react";

type Floor = { floor: string; available: number; expired: boolean };

export default function App() {
  const [floors, setFloors] = useState<Floor[]>([]);
  const [error, setError] = useState("");
  async function load() {
    try {
      const response = await fetch("/api/seats");
      if (!response.ok) throw new Error("查询失败");
      const result = await response.json();
      setFloors(result.data);
      setError("");
    } catch (failure) { setError(String(failure)); }
  }
  useEffect(() => { void load(); }, []);
  async function report(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/seats", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user: fields.get("user"), floor: fields.get("floor"), seats: Number(fields.get("seats")) }) });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "上报失败");
      await load();
    } catch (failure) { setError(String(failure)); }
  }
  return <main><h1>自习室座位</h1>{error && <p role="alert">{error}</p>}
    <button onClick={load}>刷新</button>
    <form onSubmit={report}>
      <label>账号<input name="user" required /></label>
      <label>楼层<input name="floor" required /></label>
      <label>剩余座位<input name="seats" type="number" min="0" required /></label>
      <button type="submit">上报</button>
    </form>
    {floors.map(row => <p key={row.floor}>{row.floor} · {row.expired ? "已过期" : row.available}</p>)}
  </main>;
}
'''),
}
