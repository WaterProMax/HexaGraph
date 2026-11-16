# Task 1: 导入可查询、总时限、去重、取消 + 前端整理等待

Work from: `/Users/cenghuanxiao/Desktop/HexaGraph`

Branch: `feat/display-stability-ux` (already checked out)

Plan: `Test3/docs/superpowers/plans/2026-11-16-display-stability.md`

## Context

Today `Workbench.create_design_run` creates a run with `design_input_status=importing`, then **awaits both** `intake_spec` and `intake_design` before returning. The HTTP client blocks; UI only has a button spinner. Run already exists on disk via `emit` → `_persist_snapshot` (reuse this; see PR #25 patterns — atomic snapshot/projects.json; do **not** add a second run store).

## Required behavior

### Backend

1. After validate + create run + persist `design_input` + set `importing`, **return immediately** with `status="importing"` and `run_id`. Continue SPEC then DESIGN intakes in an `asyncio` background task tracked on the workbench (e.g. `self._import_tasks[run_id]`).
2. Extend `DesignRunResult.status` Literal to include `"importing"` (and keep existing statuses). Response must remain compatible when import finishes synchronously in tests that await completion — callers accept either immediate complete **or** importing.
3. Artifacts (suggested keys, keep names consistent once chosen):
   - `design_input_started_at` (ISO or epoch)
   - `design_input_deadline_at` (start + 600s)
   - `design_input_step`: `"spec"` | `"design"` | `""` (or similar) — only real steps, no fake %
4. Single **600s** deadline for the whole import (both intakes + gateway retries). Injectable clock / `import_timeout_s` for tests (default 600). On expiry: cancel local await/task, set terminal failed/timeout status, **no DESIGN gate**. Late completion must check status/generation before writing success — never overwrite terminal.
5. Same project already has an active import (`importing`): HTTP **409** with safe JSON body including error category, summary, and existing `run_id`. Do not start a second LLM import.
6. `terminate` (and timeout) must cancel the in-flight import task. Note in message that provider may still bill.
7. `restore_runs`: if snapshot still `importing`, mark interrupted/failed (or equivalent terminal) so UI is not stuck forever; allow resubmit; do **not** auto-resume model calls.
8. Persist via existing `_persist_snapshot` / emit so refresh and restart see state.

### Frontend (minimal for this task)

1. `DesignSpecInput`: on submit show “正在整理…” / when step known “正在整理需求规格” / “正在整理设计规格” + elapsed seconds; disable re-submit while busy or while watching an importing run.
2. If POST returns `importing`, navigate/select that `run_id` and poll existing `api.run` / `api.artifacts` (Workstation already refreshes) until status leaves `importing` or local 10 min UX timeout.
3. `AbortController` only stops waiting on the browser; do not claim backend cancelled. On conflict 409, jump to existing `run_id`.
4. `api/client.ts`: stop collapsing all 409 to `Error("409")`; parse JSON for category/summary/`run_id` safely.
5. `DesignSpecPreview`: handle `importing` status banner.

### Out of scope for Task 1

- Full six-way error taxonomy UI (Task 2) — timeout terminal + basic failed message is enough.
- Original text restore after reload (Task 3) — keep textarea local for now.
- Demo sample matching / schedule tip (Task 4).

## Tests first (TDD)

Add/extend under `Test3/backend/tests/e2e/` (prefer next to `test_design_input.py`):

- ASAP return importing + run eventually reaches awaiting_confirmation / needs_input under scripted.
- Duplicate submit same project → 409 + same run_id.
- Short injected timeout → failed/timeout, no gate; late result ignored.
- Terminate while importing → cancelled; late success ignored.
- restore_runs with importing snapshot → not stuck importing forever.

Frontend: extend DesignSpecPreview test for `importing`; add DesignSpecInput test if feasible with fake timers for elapsed/disable.

## Verify

```bash
cd Test3/backend && uv run pytest -q -m "not live" tests/e2e/test_design_input.py tests/e2e/test_design_input_change.py
# plus any new import-lifecycle test file
cd Test3/frontend && npx tsc --noEmit && npm test -- --run
```

## Commit

Commit on `feat/display-stability-ux` with a focused message, e.g. `fix(test3): make design-spec import queryable with timeout and dedupe`.

Do **not** push. Do **not** merge others' PRs. Do **not** force-push.
