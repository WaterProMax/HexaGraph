from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from app.errors import CommandDenied, WriteDenied
from app.tools.sandbox import in_write_set, normalize_under, run_command


def _tool_spec(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


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
        forbidden: list[str] | None = None,
    ) -> None:
        self.root = root
        self.write_set = write_set
        self.whitelist = whitelist
        self.forbidden = list(forbidden or [])
        self.timeout = timeout
        self.env_allow = env_allow
        self.truncate = truncate
        self.on_denied = on_denied
        self.written: list[str] = []
        self.denied: list[str] = []
        self.specs = [
            _tool_spec(
                "write_file",
                "Write a text file inside the task write_set.",
                {"path": {"type": "string"}, "content": {"type": "string"}},
                ["path", "content"],
            ),
            _tool_spec(
                "run_command",
                "Run a whitelisted command in the task workspace.",
                {
                    "cmd": {"type": "array", "items": {"type": "string"}},
                    "command": {"type": "array", "items": {"type": "string"}},
                },
                ["cmd"],
            ),
            _tool_spec(
                "read_file",
                "Read a text file under the task workspace.",
                {"path": {"type": "string"}},
                ["path"],
            ),
            _tool_spec(
                "list_dir",
                "List entries in a directory under the task workspace.",
                {"path": {"type": "string"}},
                [],
            ),
        ]

    @staticmethod
    def _command_args(args: dict[str, Any]) -> list[str]:
        """兼容模型传命令的三种写法：数组、JSON 字符串数组、空白分隔的普通字符串。"""
        raw: Any = args.get("cmd") or args.get("command") or []
        if isinstance(raw, list):
            return [str(part) for part in raw]
        text = str(raw).strip()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(part) for part in parsed]
        return text.split() if text else []

    async def execute(self, name: str, arguments: dict[str, Any] | None) -> Any:
        args = arguments or {}
        if name == "write_file":
            return self._write_file(str(args.get("path") or ""), str(args.get("content") or ""))
        if name == "run_command":
            cmd = self._command_args(args)
            try:
                return await run_command(
                    cmd,
                    cwd=self.root,
                    whitelist=self.whitelist,
                    timeout=self.timeout,
                    env_allow=self.env_allow,
                    truncate=self.truncate,
                    forbidden=self.forbidden,
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
