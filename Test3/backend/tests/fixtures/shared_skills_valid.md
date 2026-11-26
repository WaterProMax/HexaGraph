# Shared skills bundle

Curated, public shared skills for offline task context.

<!-- HEXAGRAPH_SHARED_SKILLS_V1 -->

```json
{
  "schema_version": 1,
  "bundle_version": "2026.11.25",
  "entries": [
    {
      "id": "python-focused-impl",
      "version": "1.2.0",
      "source_kind": "github_curated",
      "source_revision": "9f3c1a2b4d5e6f708192a3b4c5d6e7f8091a2b3c",
      "source_url": "https://github.com/obra/superpowers/blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/skills/example/SKILL.md",
      "license": "MIT",
      "attribution": "Copyright (c) fixture authors",
      "content_sha256": "adf10eed7a279aa7fd6d13a97fcc0d810ee04fda8c38697fdfc7d7a305f67d14",
      "task_types": [
        "impl"
      ],
      "tags": [
        "python",
        "pytest"
      ],
      "priority": 80,
      "summary": "Scoped implementation workflow for Python modules.",
      "body_md": "## Implementation mode\n\n1. Read the existing module before editing it.\n2. Keep the change scoped to the declared files.\n3. Run the focused unit tests before reporting results."
    },
    {
      "id": "pytest-regression-guide",
      "version": "1.0.3",
      "source_kind": "github_curated",
      "source_revision": "4c8d2e0f1a3b5c7d9e0f1a2b3c4d5e6f708192a3",
      "source_url": "https://github.com/obra/superpowers/blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/skills/example/SKILL.md",
      "license": "MIT",
      "attribution": "Copyright (c) fixture authors",
      "content_sha256": "caeea69af127f2d1eda67d270dd83ca850a88bd52dbba27ecdf5c7df609860b2",
      "task_types": [
        "test"
      ],
      "tags": [
        "python",
        "testing"
      ],
      "priority": 60,
      "summary": "Offline pytest conventions for new tests.",
      "body_md": "## Python testing notes\n\nPrefer the project virtualenv when running the test suite, and keep new tests deterministic and offline."
    },
    {
      "id": "docs-release-notes",
      "version": "0.9.0",
      "source_kind": "github_curated",
      "source_revision": "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678",
      "source_url": "https://github.com/obra/superpowers/blob/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/skills/example/SKILL.md",
      "license": "MIT",
      "attribution": "Copyright (c) fixture authors",
      "content_sha256": "97747e5cd703eec87f112d0e95b39429d5c8f12f914921ad31570eb1c03b8c47",
      "task_types": [
        "doc"
      ],
      "tags": [
        "documentation"
      ],
      "priority": 40,
      "summary": "How to update release notes.",
      "body_md": "## Documentation notes\n\nUpdate user-visible docs whenever a public behaviour changes, and keep examples runnable without network access."
    }
  ]
}
```

The prose above and below the JSON block is informational only.
