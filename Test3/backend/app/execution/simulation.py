"""Execution capability policy: model mode is not executor capability.

Product default: real executor.  Only an explicitly injected test policy may
enable a side-effect-free simulated executor or authorize local test execution;
neither is reachable from HTTP, settings or environment variables.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPolicy:
    simulated: bool = False
    # Test-only: authorize the legacy local executor in isolated tmp workspaces.
    local_execution_authorized: bool = False

    @property
    def capability(self) -> str:
        if self.simulated:
            return "none"
        return "local_workspace_write+subprocess+git+egress_network"


DEFAULT_POLICY = ExecutionPolicy()


class SimulatedExecutor:
    """No filesystem writes, no git, no subprocesses, no network."""

    capability = "none"

    def execute(self, run, task, card) -> dict:
        return {
            "kind": "simulated",
            "summary": f"模拟执行 {card.code}",
            "path": "",
        }

    def verify(self, task) -> bool:
        evidence = task.get("evidence") or []
        return any(
            isinstance(item, dict) and item.get("kind") == "simulated" for item in evidence
        )


__all__ = ["DEFAULT_POLICY", "ExecutionPolicy", "SimulatedExecutor"]