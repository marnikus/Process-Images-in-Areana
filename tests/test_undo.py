import shutil
from pathlib import Path
from app.persistence.config_manager import ConfigManager
from app.core.undo_service import UndoService

def test_undo_push_undo_redo(tmp_path=None):
    # use temp dir
    import tempfile
    td = Path(tempfile.mkdtemp())
    try:
        cm = ConfigManager(str(td))
        us = UndoService(cm.undo)
        # push urls
        us.push('urls', [{'id':'1','url':'https://a.com'}])
        hist, idx = us.history()
        assert len(hist) == 1
        assert idx == 0

        us.push('urls', [{'id':'1','url':'https://a.com'},{'id':'2','url':'https://b.com'}])
        hist, idx = us.history()
        assert len(hist) == 2
        assert idx == 1

        # undo
        res = us.undo()
        assert res is not None
        assert res['index'] == 0
        hist, idx = us.history()
        assert idx == 0

        # redo
        res = us.redo()
        assert res is not None
        assert res['index'] == 1

        # push after undo should drop redo tail
        us.undo()
        hist, idx = us.history()
        assert idx == 0
        us.push('prompt', 'new prompt')
        hist, idx = us.history()
        assert len(hist) == 2  # old second dropped
        assert idx == 1
        assert hist[1]['kind'] == 'prompt'

        # cap at 100
        for i in range(150):
            us.push('grid', f'payload_{i}')
        hist, idx = us.history()
        assert len(hist) <= 100
    finally:
        shutil.rmtree(td)

def test_undo_store_persistence():
    import tempfile
    td = Path(tempfile.mkdtemp())
    try:
        cm = ConfigManager(str(td))
        us = UndoService(cm.undo)
        us.push('settings', {'a':1})
        us.push('urls', [{'url':'https://x'}])
        # reload
        cm2 = ConfigManager(str(td))
        us2 = UndoService(cm2.undo)
        hist, idx = us2.history()
        assert len(hist) == 2
        assert idx == 1
    finally:
        shutil.rmtree(td)
