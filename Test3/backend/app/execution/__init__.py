"""Execution-grant domain: scope policy, persistence, isolated execution.

The new domain owns its SQLite tables (see contracts C.6). Legacy runs keep
their JSONL/snapshot storage; nothing here rewrites legacy artifacts.
"""