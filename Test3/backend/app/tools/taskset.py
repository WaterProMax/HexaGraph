from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app.errors import CommandDenied, WriteDenied
from app.tools.sandbox import in_write_set, normalize_under, run_command


class TaskToolset:
    def __init__(
        self,
        root: Path,
        write_set: list[str],
        *,
        whitelist: list[str],
        timeout: int,
        env_allow: list[str],
        truncate: int,
        on_denied: Callable[[str, str], None] | None = None,
    ) -> None:
        self.root = root
        self.write_set = write_set
        self.whitelist = whitelist
        self.timeout = timeout
        self.env_allow = env_allow
        self.truncate = truncate
        self.on_denied = on_denied
        self.written: list[str] = []
        self.denied: list[str] = []
        self.specs = [
            {"type": "function", "function": {"name": "write_file", "parameters": {"type": "object"}}},
            {"type": "function", "function": {"name": "run_command", "parameters": {"type": "object"}}},
            {"type": "function", "function": {"name": "read_file", "parameters": {"type": "object"}}},
            {"type": "function", "function": {"name": "list_dir", "parameters": {"type": "object"}}},
        ]

    async def execute(self, name: str, arguments: dict[str, Any] | None) -> Any:
        args = arguments or {}
        if name == "write_file":
            return self._write_file(str(args.get("path") or ""), str(args.get("content") or ""))
        if name == "run_command":
            cmd = args.get("cmd") or args.get("command") or []
            if isinstance(cmd, str):
                cmd = cmd.split()
            try:
                return await run_command(
                    list(cmd),
                    cwd=self.root,
                    whitelist=self.whitelist,
                    timeout=self.timeout,
                    env_allow=self.env_allow,
                    truncate=self.truncate,
                )
            except CommandDenied as exc:
                if self.on_denied:
                    self.on_denied("command", " ".join(str(part) for part in cmd))
                return {"ok": False, "error": str(exc), "denied": True}
        if name == "read_file":
            path = normalize_under(self.root, str(args.get("path") or ""))
            return path.read_text(encoding="utf-8") if path.exists() else ""
        if name == "list_dir":
            path = normalize_under(self.root, str(args.get("path") or "."))
            if not path.exists():
                return []
            return [p.name for p in path.iterdir()]
        return {"error": f"unknown tool {name}"}

    def _write_file(self, rel: str, content: str) -> dict[str, Any]:
        try:
            path = normalize_under(self.root, rel)
            if not in_write_set(path, self.root, self.write_set):
                self.denied.append(rel)
                if self.on_denied:
                    self.on_denied("write", rel)
                raise WriteDenied(f"写集外: {rel}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            self.written.append(rel)
            return {"ok": True, "path": rel}
        except (WriteDenied, CommandDenied) as exc:
            self.denied.append(rel)
            if self.on_denied:
                self.on_denied("write", rel)
            return {"ok": False, "error": str(exc)}
