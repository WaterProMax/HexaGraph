"""Dedicated offline server; never inherit model credentials or user's data."""
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
    with tempfile.TemporaryDirectory(prefix='hexagraph-e2e-') as data:
        os.environ['TEST3_DATA_DIR'] = data
        uvicorn.run('app.main:app', host='127.0.0.1', port=8765)
