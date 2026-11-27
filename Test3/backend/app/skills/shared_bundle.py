"""Parse and select entries from an offline shared-skill Markdown bundle.

A bundle is a single Markdown document that contains exactly one HTML marker
and, after it, exactly one ``json`` fenced block.  The JSON block carries the
curated entries; the rest of the document is human-readable prose.

Design constraints for this module:

* it is a pure parser/selector: no network access, and no file I/O except the
  explicit :func:`load_shared_bundle` helper;
* every validation failure rejects the whole bundle by raising
  :class:`SharedSkillError`, never by returning a partially parsed result;
* selection is deterministic so repeated calls with the same inputs return
  byte-for-byte identical sections.

Only public, curated content is accepted (``source_kind`` must be
``"github_curated"``).  Project memory and experience cards are intentionally
out of scope: this parser has no adapter for either.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.agents.task_context import ContextSection

MARKER = "<!-- HEXAGRAPH_SHARED_SKILLS_V1 -->"
SCHEMA_VERSION = 1
SOURCE_KIND = "github_curated"

MAX_BUNDLE_BYTES = 512 * 1024  # 512 KiB of UTF-8 Markdown
MIN_ENTRIES = 1
MAX_ENTRIES = 32
MAX_BODY_CHARS = 12_000
MAX_SUMMARY_CHARS = 500
MAX_SELECTED_SECTIONS = 4
MAX_SELECTED_CHARS = 6_000

ALLOWED_TASK_TYPES = frozenset(
    {"scaffold", "stub", "impl", "test", "integration", "spike", "doc"}
)

BUNDLE_FIELDS = frozenset({"schema_version", "bundle_version", "entries"})
ENTRY_FIELDS = frozenset(
    {
        "id",
        "version",
        "source_kind",
        "source_revision",
        "content_sha256",
        "source_url",
        "license",
        "attribution",
        "task_types",
        "tags",
        "priority",
        "summary",
        "body_md",
    }
)

_SOURCE_REVISION = re.compile(r"^[0-9a-fA-F]{40}$")
_CONTENT_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class SharedSkillError(Exception):
    """A bundle was rejected.

    ``category`` is a stable machine-readable reason (for example
    ``"duplicate_json_key"``) and ``message`` is a human-readable detail.
    """

    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message


@dataclass(frozen=True)
class SharedSkillEntry:
    """One validated shared-skill entry."""

    id: str
    version: str
    source_kind: str
    source_revision: str
    content_sha256: str
    source_url: str
    license: str
    attribution: str
    task_types: tuple[str, ...]
    tags: tuple[str, ...]
    priority: int
    summary: str
    body_md: str


@dataclass(frozen=True)
class SharedSkillBundle:
    """A parsed, self-consistent shared-skill bundle."""

    schema_version: int
    bundle_version: str
    entries: tuple[SharedSkillEntry, ...]
    sha256: str
    path: Path | None = None


class _DuplicateJsonKey(Exception):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _fail(category: str, message: str) -> None:
    raise SharedSkillError(category, message)


def canonical_body_md(body_md: str) -> str:
    """Return the canonical form of an entry body used by ``content_sha256``.

    Canonicalisation only normalises line endings to ``\\n``; the visible
    characters (including leading/trailing whitespace) are preserved.  Fixture
    bodies therefore hash exactly as their JSON string content.
    """

    return body_md.replace("\r\n", "\n").replace("\r", "\n")


def compute_content_sha256(body_md: str) -> str:
    """Return the canonical ``content_sha256`` for ``body_md``."""

    return hashlib.sha256(canonical_body_md(body_md).encode("utf-8")).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_string(value: Any, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        _fail("invalid_field", f"{field} must be a string")
    if not allow_empty and not value.strip():
        _fail("invalid_field", f"{field} must not be empty")
    return value


def _require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("invalid_field", f"{field} must be a JSON object")
    return value


def _check_fields(
    obj: dict[str, Any], required: frozenset[str], where: str
) -> None:
    missing = sorted(required - set(obj))
    if missing:
        _fail("missing_field", f"{where} is missing required field(s): {', '.join(missing)}")
    extra = sorted(set(obj) - required)
    if extra:
        _fail("unknown_field", f"{where} has unknown field(s): {', '.join(extra)}")


def _find_json_fences(markdown: str) -> list[tuple[int, str]]:
    """Return ``(start_offset, content)`` for every ```json fenced block."""

    blocks: list[tuple[int, str]] = []
    offset = 0
    lines = markdown.splitlines(keepends=True)
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "```json":
            start = offset
            content_lines: list[str] = []
            offset += len(line)
            index += 1
            closed = False
            while index < len(lines):
                body_line = lines[index]
                if body_line.strip().startswith("```"):
                    offset += len(body_line)
                    index += 1
                    closed = True
                    break
                content_lines.append(body_line)
                offset += len(body_line)
                index += 1
            if not closed:
                _fail("unclosed_json_block", "the json fenced block is not closed")
            blocks.append((start, "".join(content_lines)))
            continue
        offset += len(line)
        index += 1
    return blocks


def _load_json(content: str) -> Any:
    try:
        return json.loads(content, object_pairs_hook=_object_pairs_hook)
    except _DuplicateJsonKey as exc:
        raise SharedSkillError(
            "duplicate_json_key", f"duplicate JSON object key: {exc.key}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SharedSkillError("invalid_json", f"invalid JSON: {exc.msg}") from exc
    except (RecursionError, ValueError, OverflowError) as exc:
        # Deeply nested JSON and Python's integer-string limit raise outside
        # json.JSONDecodeError; normalize them so the bundle still fails closed.
        raise SharedSkillError("invalid_json", "invalid JSON structure") from exc


def _parse_entry(raw: Any, index: int) -> SharedSkillEntry:
    where = f"entries[{index}]"
    entry = _require_object(raw, where)
    _check_fields(entry, ENTRY_FIELDS, where)

    entry_id = _require_string(entry["id"], f"{where}.id")
    version = _require_string(entry["version"], f"{where}.version")

    source_kind = _require_string(entry["source_kind"], f"{where}.source_kind")
    if source_kind != SOURCE_KIND:
        _fail(
            "invalid_enum",
            f"{where}.source_kind must be {SOURCE_KIND!r}, got {source_kind!r}",
        )

    revision = _require_string(entry["source_revision"], f"{where}.source_revision")
    if not _SOURCE_REVISION.match(revision):
        _fail(
            "invalid_source_revision",
            f"{where}.source_revision must be a 40-character hex revision",
        )

    source_url = _require_string(entry["source_url"], f"{where}.source_url")
    if not source_url.startswith("https://github.com/"):
        _fail("invalid_source_url", f"{where}.source_url must be an https://github.com/ URL")
    license_name = _require_string(entry["license"], f"{where}.license")
    attribution = _require_string(
        entry["attribution"], f"{where}.attribution", allow_empty=True
    )

    content_sha = _require_string(
        entry["content_sha256"], f"{where}.content_sha256"
    )
    if not _CONTENT_SHA256.match(content_sha):
        _fail(
            "invalid_content_hash",
            f"{where}.content_sha256 must be a 64-character hex digest",
        )

    task_types_raw = entry["task_types"]
    if not isinstance(task_types_raw, list):
        _fail("invalid_field", f"{where}.task_types must be a list")
    task_types: list[str] = []
    for item in task_types_raw:
        task_type = _require_string(item, f"{where}.task_types[]")
        if task_type not in ALLOWED_TASK_TYPES:
            _fail(
                "invalid_enum",
                f"{where}.task_types contains unsupported value {task_type!r}",
            )
        task_types.append(task_type)

    tags_raw = entry["tags"]
    if not isinstance(tags_raw, list):
        _fail("invalid_field", f"{where}.tags must be a list")
    tags: list[str] = []
    for item in tags_raw:
        tag = _require_string(item, f"{where}.tags[]")
        tags.append(tag)

    priority = entry["priority"]
    if not _is_int(priority) or not 0 <= priority <= 100:
        _fail("invalid_field", f"{where}.priority must be an integer in 0..100")

    summary = _require_string(entry["summary"], f"{where}.summary", allow_empty=True)
    if len(summary) > MAX_SUMMARY_CHARS:
        _fail(
            "summary_too_long",
            f"{where}.summary must be at most {MAX_SUMMARY_CHARS} characters",
        )

    body_md = _require_string(entry["body_md"], f"{where}.body_md", allow_empty=True)
    if len(body_md) > MAX_BODY_CHARS:
        _fail(
            "body_too_long",
            f"{where}.body_md must be at most {MAX_BODY_CHARS} characters",
        )

    expected = compute_content_sha256(body_md)
    if content_sha.lower() != expected:
        _fail(
            "content_hash_mismatch",
            f"{where}.content_sha256 does not match its canonical body_md",
        )

    return SharedSkillEntry(
        id=entry_id,
        version=version,
        source_kind=source_kind,
        source_revision=revision.lower(),
        content_sha256=content_sha.lower(),
        source_url=source_url,
        license=license_name,
        attribution=attribution,
        task_types=tuple(task_types),
        tags=tuple(tags),
        priority=priority,
        summary=summary,
        body_md=body_md,
    )


def _entry_payload(entry: SharedSkillEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "version": entry.version,
        "source_kind": entry.source_kind,
        "source_revision": entry.source_revision,
        "content_sha256": entry.content_sha256,
        "source_url": entry.source_url,
        "license": entry.license,
        "attribution": entry.attribution,
        "task_types": list(entry.task_types),
        "tags": list(entry.tags),
        "priority": entry.priority,
        "summary": entry.summary,
        "body_md": entry.body_md,
    }


def _bundle_sha256(
    schema_version: int,
    bundle_version: str,
    entries: tuple[SharedSkillEntry, ...],
) -> str:
    payload = {
        "schema_version": schema_version,
        "bundle_version": bundle_version,
        "entries": [_entry_payload(entry) for entry in entries],
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_shared_bundle(markdown: str) -> SharedSkillBundle:
    """Parse ``markdown`` into a fully validated :class:`SharedSkillBundle`.

    Every problem raises :class:`SharedSkillError` with a stable ``category``.
    """

    if not isinstance(markdown, str):
        _fail("invalid_argument", "markdown must be a string")
    try:
        encoded = markdown.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SharedSkillError("invalid_encoding", "markdown is not valid UTF-8") from exc
    if len(encoded) > MAX_BUNDLE_BYTES:
        _fail(
            "bundle_too_large",
            f"markdown must be at most {MAX_BUNDLE_BYTES} bytes",
        )

    marker_count = markdown.count(MARKER)
    if marker_count == 0:
        _fail("missing_marker", f"bundle is missing {MARKER}")
    if marker_count > 1:
        _fail("duplicate_marker", "bundle may contain only one shared-skill marker")

    marker_offset = markdown.index(MARKER)
    blocks = _find_json_fences(markdown)
    if not blocks:
        _fail("missing_json_block", "bundle is missing its ```json block")
    if len(blocks) > 1:
        _fail("multiple_json_blocks", "bundle may contain only one ```json block")
    block_offset, block_content = blocks[0]
    if block_offset < marker_offset:
        _fail(
            "missing_json_block",
            "the ```json block must appear after the shared-skill marker",
        )

    data = _load_json(block_content)
    if not isinstance(data, dict):
        _fail("invalid_bundle", "the JSON block must be an object")
    _check_fields(data, BUNDLE_FIELDS, "bundle")

    schema_version = data["schema_version"]
    if not _is_int(schema_version):
        _fail("invalid_field", "schema_version must be an integer")
    if schema_version != SCHEMA_VERSION:
        _fail(
            "unknown_schema_version",
            f"unsupported schema_version {schema_version!r}; only {SCHEMA_VERSION} is accepted",
        )

    bundle_version = _require_string(data["bundle_version"], "bundle_version")

    entries_raw = data["entries"]
    if not isinstance(entries_raw, list):
        _fail("invalid_field", "entries must be a list")
    if len(entries_raw) < MIN_ENTRIES:
        _fail("too_few_entries", f"bundle must contain at least {MIN_ENTRIES} entry")
    if len(entries_raw) > MAX_ENTRIES:
        _fail("too_many_entries", f"bundle must contain at most {MAX_ENTRIES} entries")

    entries: list[SharedSkillEntry] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(entries_raw):
        entry = _parse_entry(raw, index)
        if entry.id in seen_ids:
            _fail("duplicate_entry_id", f"duplicate entry id: {entry.id}")
        seen_ids.add(entry.id)
        entries.append(entry)

    frozen_entries = tuple(entries)
    return SharedSkillBundle(
        schema_version=schema_version,
        bundle_version=bundle_version,
        entries=frozen_entries,
        sha256=_bundle_sha256(schema_version, bundle_version, frozen_entries),
    )


def select_shared_skills(
    bundle: SharedSkillBundle,
    *,
    task_type: str,
    tags: tuple[str, ...],
    budget_chars: int,
) -> tuple[ContextSection, ...]:
    """Select at most four shared-skill sections deterministically.

    Ranking key: an exact ``task_type`` match first, then the number of
    intersecting tags (descending), then ``priority`` (descending), then
    ``id`` (ascending).  Entries that match neither the task type nor any tag
    are omitted; entries sharing a ``content_sha256`` are deduplicated after
    ranking, keeping the best-ranked copy.
    """

    if budget_chars <= 0:
        return ()

    requested_tags = {tag for tag in tags if isinstance(tag, str)}
    ranked: list[tuple[tuple[int, int, int, str], SharedSkillEntry]] = []
    for entry in bundle.entries:
        exact = task_type in entry.task_types
        intersection = len(set(entry.tags) & requested_tags)
        if not exact and intersection == 0:
            continue
        key = (0 if exact else 1, -intersection, -entry.priority, entry.id)
        ranked.append((key, entry))
    ranked.sort(key=lambda item: item[0])

    # Deduplicate after ranking so the best-ranked copy of identical content is
    # always the one that survives, even when it does not fit the budget.
    unique: list[SharedSkillEntry] = []
    seen_hashes: set[str] = set()
    for _, entry in ranked:
        if entry.content_sha256 in seen_hashes:
            continue
        seen_hashes.add(entry.content_sha256)
        unique.append(entry)

    remaining = min(int(budget_chars), MAX_SELECTED_CHARS)
    sections: list[ContextSection] = []
    for entry in unique:
        if len(sections) >= MAX_SELECTED_SECTIONS:
            break
        if len(entry.body_md) > remaining:
            continue
        remaining -= len(entry.body_md)
        sections.append(
            ContextSection.create(
                "shared_skill",
                entry.id,
                entry.version,
                entry.body_md,
                summary=entry.summary,
            )
        )
    return tuple(sections)


def load_shared_bundle(path: Path) -> SharedSkillBundle | None:
    """Load a bundle from ``path``.

    Returns ``None`` when the file does not exist.  Invalid content raises
    :class:`SharedSkillError`; no network access is performed.
    """

    bundle_path = Path(path)
    try:
        if not bundle_path.exists():
            return None
        if bundle_path.stat().st_size > MAX_BUNDLE_BYTES:
            raise SharedSkillError(
                "bundle_too_large",
                f"markdown must be at most {MAX_BUNDLE_BYTES} bytes",
            )
        data = bundle_path.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SharedSkillError("io_error", f"cannot read shared-skill bundle: {exc}") from exc
    try:
        markdown = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SharedSkillError("invalid_encoding", "bundle is not UTF-8 text") from exc
    bundle = parse_shared_bundle(markdown)
    return replace(bundle, path=bundle_path)


__all__ = [
    "ALLOWED_TASK_TYPES",
    "ENTRY_FIELDS",
    "MARKER",
    "MAX_BODY_CHARS",
    "MAX_BUNDLE_BYTES",
    "MAX_ENTRIES",
    "MAX_SELECTED_CHARS",
    "MAX_SELECTED_SECTIONS",
    "MAX_SUMMARY_CHARS",
    "SCHEMA_VERSION",
    "SOURCE_KIND",
    "SharedSkillBundle",
    "SharedSkillEntry",
    "SharedSkillError",
    "canonical_body_md",
    "compute_content_sha256",
    "load_shared_bundle",
    "parse_shared_bundle",
    "select_shared_skills",
]