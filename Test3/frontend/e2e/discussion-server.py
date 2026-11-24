"""Dedicated offline server for the discussion E2E case; never inherit credentials or data."""
import os
import tempfile
from pathlib import Path

os.environ['TEST3_LLM_PROVIDER'] = 'scripted'
os.environ['TEST3_SCRIPTED_FIXTURE'] = 'discussion-e2e'
os.environ['DASHSCOPE_API_KEY'] = ''
os.environ['OPENAI_API_KEY'] = ''

if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
    import uvicorn
    from app.execution.simulation import ExecutionPolicy
    from app.main import create_app
    with tempfile.TemporaryDirectory(prefix='hexagraph-discussion-e2e-') as data:
        os.environ['TEST3_DATA_DIR'] = data
        # Side-effect-free executor: this E2E must not write a repo, run commands
        # or merge branches. Product defaults remain the real executor.
        app = create_app(execution_policy=ExecutionPolicy(simulated=True))
        uvicorn.run(app, host='127.0.0.1', port=8766)