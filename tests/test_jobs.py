import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from qunhuibao.jobs import tick

class JobsTests(unittest.TestCase):
    def test_skip_checkpoint_and_failed_run_keeps_previous(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config={'state_dir':str(root/'state'),'agent_command':[sys.executable,'-c','from pathlib import Path; import sys; Path(sys.argv[1],"job.json").write_text(\'{"skip":true,"reason":"没有有效内容"}\',encoding="utf-8")','{out}'],'groups':[{'id':'a'*24,'name':'演示','time':'20:00','start':'2026-11-06T20:00:00+08:00'}]}
            path=root/'config.json';path.write_text(json.dumps(config),encoding='utf-8')
            now=dt.datetime.fromisoformat('2026-11-07T21:00:00+08:00')
            self.assertEqual(tick(path,now)['results'][0]['status'],'skipped')
            self.assertEqual(tick(path,now)['results'],[])
            previous=(root/'state/state.json').read_text(encoding='utf-8')
            config['agent_command']=[sys.executable,'-c','raise SystemExit(2)'];path.write_text(json.dumps(config),encoding='utf-8')
            self.assertEqual(tick(path,now+dt.timedelta(days=1))['results'][0]['status'],'failed')
            self.assertEqual((root/'state/state.json').read_text(encoding='utf-8'),previous)

    def test_parallel_tick_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'running.lock').touch();path=root/'config.json';path.write_text(json.dumps({'state_dir':tmp}))
            with self.assertRaises(ValueError): tick(path)
