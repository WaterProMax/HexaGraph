"""Dedicated offline server; never inherit model credentials or user's data.

TEST-ONLY execution policy (E2E only, never a product default):

``ExecutionPolicy(local_execution_authorized=True)`` models the policy bit for
"this host has already authorized local execution in an isolated tmp workspace".
It is intentionally *not* ``simulated=True``: simulated runs record zero steps,
which would make the workstation's execution-trace view unverifiable. With the
local executor enabled, the legacy + scripted provider queue drives the real
code path (real worktree, real write_file tool loop, real trace collection) in
the temporary data dir below.

What stays closed: ``Workbench.execution_safety_ready`` remains False and the
granted_v1 safety gate is never opened; no real provider is configured (the
scripted provider is pinned and every credential variable is blanked); no
``models.yaml`` / ``app/`` default is touched. This mirrors the test-only
``ExecutionPolicy`` used by backend tests (``tests/e2e/test_must_fixes.py``)
and by ``e2e/discussion-server.py`` for its scripted fixture.
"""
import os
import tempfile
from pathlib import Path

os.environ['TEST3_LLM_PROVIDER'] = 'scripted'
os.environ['TEST3_SCRIPTED_FIXTURE'] = 'study-room'
os.environ['DASHSCOPE_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
    import uvicorn
    from app.execution.simulation import ExecutionPolicy
    from app.main import create_app

    with tempfile.TemporaryDirectory(prefix='hexagraph-e2e-') as data:
        os.environ['TEST3_DATA_DIR'] = data
        app = create_app(execution_policy=ExecutionPolicy(local_execution_authorized=True))
        # Port is overridable so the integration suite can avoid a local dev
        # stack that already owns the documented 8765 pair.
        port = int(os.environ.get('TEST3_E2E_API_PORT', '8765'))
        uvicorn.run(app, host='127.0.0.1', port=port)
