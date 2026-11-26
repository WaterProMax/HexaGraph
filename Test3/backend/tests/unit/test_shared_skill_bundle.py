"""Unit tests for the offline shared-skill bundle parser and selector."""

from __future__ import annotations

import hashlib
import inspect
import json
import socket
from pathlib import Path

import pytest

from app.agents.task_context import ContextSection
from app.skills.shared_bundle import (
    MARKER,
    MAX_BODY_CHARS,
    MAX_BUNDLE_BYTES,
    MAX_SELECTED_CHARS,
    MAX_SELECTED_SECTIONS,
    SharedSkillBundle,
    SharedSkillError,
    _load_json,
    load_shared_bundle,
    parse_shared_bundle,
    select_shared_skills,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
VALID_FIXTURE = FIXTURES / "shared_skills_valid.md"
DUPLICATE_FIXTURE = FIXTURES / "shared_skills_duplicate.md"
BAD_HASH_FIXTURE = FIXTURES / "shared_skills_bad_hash.md"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _entry(**overrides: object) -> dict[str, object]:
    body = str(overrides.pop("body_md", "Body text"))
    data: dict[str, object] = {
        "id": "skill-1",
        "version": "1.0.0",
        "source_kind": "github_curated",
        "source_revision": "a" * 40,
        "source_url": "https://github.com/example/skills/blob/" + "a" * 40 + "/skills/demo/SKILL.md",
        "license": "MIT",
        "attribution": "Copyright (c) fixture authors",
        "task_types": ["impl"],
        "tags": ["python"],
        "priority": 50,
        "summary": "A short summary.",
        "body_md": body,
    }
    data.update(overrides)
    if "content_sha256" not in data:
        data["content_sha256"] = _sha(body)
    return data


def _payload(
    entries: list[dict[str, object]],
    *,
    schema_version: object = 1,
    bundle_version: object = "2026.11.25",
) -> str:
    return json.dumps(
        {
            "schema_version": schema_version,
            "bundle_version": bundle_version,
            "entries": entries,
        },
        ensure_ascii=False,
        indent=2,
    )


def _markdown(
    entries: list[dict[str, object]],
    *,
    marker: str | None = MARKER,
    schema_version: object = 1,
    bundle_version: object = "2026.11.25",
) -> str:
    marker_line = f"{marker}\n\n" if marker else ""
    return (
        "# Shared skills\n\n"
        "Offline fixture.\n\n"
        f"{marker_line}"
        "```json\n"
        f"{_payload(entries, schema_version=schema_version, bundle_version=bundle_version)}\n"
        "```\n"
    )


def _bundle(entries: list[dict[str, object]]) -> SharedSkillBundle:
    return parse_shared_bundle(_markdown(entries))


# ---------------------------------------------------------------------------
# Valid parsing and loading
# ---------------------------------------------------------------------------


def test_valid_fixture_parses() -> None:
    bundle = parse_shared_bundle(VALID_FIXTURE.read_text(encoding="utf-8"))
    assert bundle.schema_version == 1
    assert bundle.bundle_version == "2026.11.25"
    assert len(bundle.entries) == 3
    assert bundle.path is None
    assert [entry.id for entry in bundle.entries] == [
        "python-focused-impl",
        "pytest-regression-guide",
        "docs-release-notes",
    ]
    assert len(bundle.sha256) == 64
    for entry in bundle.entries:
        assert entry.source_kind == "github_curated"
        assert len(entry.source_revision) == 40
        assert len(entry.content_sha256) == 64
        assert entry.content_sha256 == _sha(entry.body_md)
        assert entry.body_md
        assert isinstance(entry.task_types, tuple)
        assert isinstance(entry.tags, tuple)


def test_load_valid_bundle_sets_optional_path(tmp_path: Path) -> None:
    target = tmp_path / "bundle.md"
    target.write_text(VALID_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    bundle = load_shared_bundle(target)
    assert bundle is not None
    assert bundle.path == target
    assert len(bundle.entries) == 3


def test_load_missing_returns_none(tmp_path: Path) -> None:
    assert load_shared_bundle(tmp_path / "absent.md") is None


def test_load_invalid_content_raises(tmp_path: Path) -> None:
    target = tmp_path / "invalid.md"
    target.write_text("not a shared skills bundle", encoding="utf-8")
    with pytest.raises(SharedSkillError) as excinfo:
        load_shared_bundle(target)
    assert excinfo.value.category == "missing_marker"


def test_load_non_utf8_raises(tmp_path: Path) -> None:
    target = tmp_path / "invalid.md"
    target.write_bytes(b"\xff\xfe\x00not utf-8")
    with pytest.raises(SharedSkillError) as excinfo:
        load_shared_bundle(target)
    assert excinfo.value.category == "invalid_encoding"


def test_bundle_sha256_is_stable() -> None:
    markdown = VALID_FIXTURE.read_text(encoding="utf-8")
    first = parse_shared_bundle(markdown)
    second = parse_shared_bundle(markdown)
    assert first.sha256 == second.sha256
    assert len(first.sha256) == 64
    # Rewriting the same payload with different surrounding prose and JSON
    # formatting must not change the bundle hash.
    reordered = json.loads(
        markdown.split("```json\n", 1)[1].split("\n```", 1)[0]
    )
    other_markdown = "# Different title\n\n" + MARKER + "\n\n```json\n" + json.dumps(
        reordered, ensure_ascii=False, sort_keys=True
    ) + "\n```\n"
    assert parse_shared_bundle(other_markdown).sha256 == first.sha256


# ---------------------------------------------------------------------------
# Structural rejection
# ---------------------------------------------------------------------------


def test_duplicate_json_key_rejected() -> None:
    markdown = (
        "# Bundle\n\n"
        f"{MARKER}\n\n"
        "```json\n"
        "{\n"
        '  "schema_version": 1,\n'
        '  "bundle_version": "1.0.0",\n'
        '  "bundle_version": "2.0.0",\n'
        '  "entries": []\n'
        "}\n"
        "```\n"
    )
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(markdown)
    assert excinfo.value.category == "duplicate_json_key"


def test_duplicate_entry_ids_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(DUPLICATE_FIXTURE.read_text(encoding="utf-8"))
    assert excinfo.value.category == "duplicate_entry_id"


def test_missing_marker_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([_entry()], marker=None))
    assert excinfo.value.category == "missing_marker"


def test_duplicate_marker_rejected() -> None:
    markdown = _markdown([_entry()]).replace(MARKER, f"{MARKER}\n\n{MARKER}", 1)
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(markdown)
    assert excinfo.value.category == "duplicate_marker"


def test_missing_json_block_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(f"# Bundle\n\n{MARKER}\n\nno json here\n")
    assert excinfo.value.category == "missing_json_block"


def test_json_block_before_marker_rejected() -> None:
    payload = _payload([_entry()])
    markdown = f"```json\n{payload}\n```\n\n{MARKER}\n"
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(markdown)
    assert excinfo.value.category == "missing_json_block"


def test_two_json_blocks_rejected() -> None:
    payload = _payload([_entry()])
    markdown = (
        f"# Bundle\n\n{MARKER}\n\n"
        f"```json\n{payload}\n```\n\n"
        f"```json\n{payload}\n```\n"
    )
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(markdown)
    assert excinfo.value.category == "multiple_json_blocks"


def test_unknown_schema_version_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([_entry()], schema_version=2))
    assert excinfo.value.category == "unknown_schema_version"


def test_missing_bundle_field_rejected() -> None:
    payload = json.dumps(
        {"schema_version": 1, "entries": [_entry()]}, ensure_ascii=False
    )
    markdown = f"# Bundle\n\n{MARKER}\n\n```json\n{payload}\n```\n"
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(markdown)
    assert excinfo.value.category == "missing_field"


def test_unknown_bundle_field_rejected() -> None:
    payload = json.dumps(
        {
            "schema_version": 1,
            "bundle_version": "1.0.0",
            "entries": [_entry()],
            "unexpected": True,
        },
        ensure_ascii=False,
    )
    markdown = f"# Bundle\n\n{MARKER}\n\n```json\n{payload}\n```\n"
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(markdown)
    assert excinfo.value.category == "unknown_field"


def test_missing_entry_field_rejected() -> None:
    entry = _entry()
    del entry["body_md"]
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([entry]))
    assert excinfo.value.category == "missing_field"


def test_unknown_entry_field_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([_entry(extra="nope")]))
    assert excinfo.value.category == "unknown_field"


@pytest.mark.parametrize(
    "overrides",
    [
        {"source_kind": "project_memory"},
        {"task_types": ["deploy"]},
    ],
)
def test_invalid_enum_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([_entry(**overrides)]))
    assert excinfo.value.category == "invalid_enum"


@pytest.mark.parametrize(
    ("field", "value", "category"),
    [
        ("source_revision", "abc123", "invalid_source_revision"),
        ("source_revision", "z" * 40, "invalid_source_revision"),
        ("content_sha256", "abc", "invalid_content_hash"),
        ("content_sha256", "z" * 64, "invalid_content_hash"),
        ("priority", 101, "invalid_field"),
        ("priority", -1, "invalid_field"),
        ("priority", True, "invalid_field"),
        ("tags", "python", "invalid_field"),
        ("task_types", "impl", "invalid_field"),
    ],
)
def test_invalid_entry_values_rejected(
    field: str, value: object, category: str
) -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([_entry(**{field: value})]))
    assert excinfo.value.category == category


# ---------------------------------------------------------------------------
# Content hashes and limits
# ---------------------------------------------------------------------------


def test_bad_hash_fixture_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(BAD_HASH_FIXTURE.read_text(encoding="utf-8"))
    assert excinfo.value.category == "content_hash_mismatch"


def test_missing_content_hash_rejected() -> None:
    entry = _entry()
    del entry["content_sha256"]
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([entry]))
    assert excinfo.value.category == "missing_field"


def test_content_hash_mismatch_rejected() -> None:
    entry = _entry(content_sha256=_sha("a different body"))
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([entry]))
    assert excinfo.value.category == "content_hash_mismatch"


def test_content_hash_uses_canonical_lf_newlines() -> None:
    body = "line one\r\nline two"
    entry = _entry(body_md=body, content_sha256=_sha("line one\nline two"))
    bundle = parse_shared_bundle(_markdown([entry]))
    assert bundle.entries[0].body_md == body


def test_oversize_body_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([_entry(body_md="x" * (MAX_BODY_CHARS + 1))]))
    assert excinfo.value.category == "body_too_long"


def test_body_at_limit_is_accepted() -> None:
    body = "x" * MAX_BODY_CHARS
    bundle = parse_shared_bundle(_markdown([_entry(body_md=body)]))
    assert len(bundle.entries[0].body_md) == MAX_BODY_CHARS


def test_oversize_markdown_rejected() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle("x" * (MAX_BUNDLE_BYTES + 1))
    assert excinfo.value.category == "bundle_too_large"


def test_entry_count_limits_enforced() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown([]))
    assert excinfo.value.category == "too_few_entries"
    too_many = [
        _entry(id=f"skill-{index}", body_md=f"body {index}") for index in range(33)
    ]
    with pytest.raises(SharedSkillError) as excinfo:
        parse_shared_bundle(_markdown(too_many))
    assert excinfo.value.category == "too_many_entries"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def _selection_bundle() -> SharedSkillBundle:
    return _bundle(
        [
            _entry(
                id="tag-only",
                task_types=["test"],
                tags=["python"],
                priority=100,
                body_md="tag only",
            ),
            _entry(
                id="exact-no-tag",
                task_types=["impl"],
                tags=["rust"],
                priority=90,
                body_md="exact no tag",
            ),
            _entry(
                id="exact-with-tag",
                task_types=["impl"],
                tags=["python"],
                priority=10,
                body_md="exact with tag",
            ),
            _entry(
                id="no-hit",
                task_types=["doc"],
                tags=["documentation"],
                priority=100,
                body_md="no hit",
            ),
        ]
    )


def test_selection_ranking_is_deterministic() -> None:
    bundle = _selection_bundle()
    sections = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=6000
    )
    assert [section.source_id for section in sections] == [
        "exact-with-tag",
        "exact-no-tag",
        "tag-only",
    ]
    assert all(section.kind == "shared_skill" for section in sections)
    assert sections[0].source_version == "1.0.0"
    assert sections[0].text == "exact with tag"
    assert sections[0].summary == "A short summary."
    assert sections[0].sha256 == _sha("exact with tag")


def test_selection_is_stable_across_calls() -> None:
    bundle = _selection_bundle()
    first = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=6000
    )
    second = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=6000
    )
    assert first == second
    assert isinstance(first, tuple)
    assert all(isinstance(section, ContextSection) for section in first)


def test_selection_dedupes_by_content_hash_keep_best() -> None:
    bundle = _bundle(
        [
            _entry(
                id="best-dupe",
                priority=90,
                body_md="same body text",
                task_types=["impl"],
                tags=["python"],
            ),
            _entry(
                id="later-dupe",
                priority=10,
                body_md="same body text",
                task_types=["impl"],
                tags=["python"],
            ),
        ]
    )
    sections = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=6000
    )
    assert [section.source_id for section in sections] == ["best-dupe"]


def test_selection_no_hit_returns_empty() -> None:
    bundle = _selection_bundle()
    assert (
        select_shared_skills(
            bundle, task_type="spike", tags=("fortran",), budget_chars=6000
        )
        == ()
    )


def test_selection_respects_budget() -> None:
    bundle = _bundle(
        [
            _entry(id="a", body_md="a" * 100, tags=["python"]),
            _entry(id="b", body_md="b" * 100, tags=["python"]),
            _entry(id="c", body_md="c" * 100, tags=["python"]),
        ]
    )
    sections = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=250
    )
    assert [section.source_id for section in sections] == ["a", "b"]
    assert sum(len(section.text) for section in sections) <= 250


def test_selection_skips_oversize_entry_and_keeps_smaller_ones() -> None:
    bundle = _bundle(
        [
            _entry(id="big", body_md="x" * 7000, tags=["python"]),
            _entry(id="small", body_md="y" * 10, tags=["python"]),
        ]
    )
    sections = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=10000
    )
    assert [section.source_id for section in sections] == ["small"]


def test_selection_caps_total_chars_at_6000() -> None:
    bundle = _bundle(
        [
            _entry(id=f"skill-{index}", body_md=("x" * 1999) + str(index), tags=["python"])
            for index in range(5)
        ]
    )
    sections = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=100_000
    )
    assert sum(len(section.text) for section in sections) <= MAX_SELECTED_CHARS
    assert len(sections) <= MAX_SELECTED_SECTIONS


def test_selection_returns_at_most_four_sections() -> None:
    bundle = _bundle(
        [
            _entry(id=f"skill-{index}", body_md=f"body {index}", tags=["python"])
            for index in range(6)
        ]
    )
    sections = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=6000
    )
    assert len(sections) == MAX_SELECTED_SECTIONS == 4


def test_selection_non_positive_budget_returns_empty() -> None:
    bundle = _selection_bundle()
    assert (
        select_shared_skills(bundle, task_type="impl", tags=(), budget_chars=0) == ()
    )


# ---------------------------------------------------------------------------
# Offline guarantee
# ---------------------------------------------------------------------------


def test_module_has_no_network_imports() -> None:
    import app.skills.shared_bundle as shared_bundle_module

    source = inspect.getsource(shared_bundle_module)
    for forbidden in (
        "import httpx",
        "import requests",
        "import socket",
        "import urllib",
        "import aiohttp",
        "http.client",
    ):
        assert forbidden not in source


def test_parse_and_select_do_not_open_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _no_socket(*args: object, **kwargs: object) -> None:
        raise AssertionError("shared bundle parsing must not use the network")

    monkeypatch.setattr(socket, "socket", _no_socket)
    bundle = parse_shared_bundle(VALID_FIXTURE.read_text(encoding="utf-8"))
    sections = select_shared_skills(
        bundle, task_type="impl", tags=("python",), budget_chars=6000
    )
    assert sections

def test_provenance_fields_are_required_and_validated() -> None:
    entry = _entry()
    del entry["license"]
    with pytest.raises(SharedSkillError) as missing:
        parse_shared_bundle(_markdown([entry]))
    assert missing.value.category == "missing_field"

    with pytest.raises(SharedSkillError) as bad_url:
        parse_shared_bundle(_markdown([_entry(source_url="https://example.com/skill")]))
    assert bad_url.value.category == "invalid_source_url"

    bundle = parse_shared_bundle(_markdown([_entry()]))
    assert bundle.entries[0].license == "MIT"
    assert bundle.entries[0].source_url.startswith("https://github.com/")


def test_deeply_nested_json_fails_closed() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        _load_json("[" * 10000 + "]" * 10000)
    assert excinfo.value.category == "invalid_json"


def test_huge_integer_literal_fails_closed() -> None:
    with pytest.raises(SharedSkillError) as excinfo:
        _load_json('{"value": ' + "9" * 5000 + "}")
    assert excinfo.value.category == "invalid_json"
