import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class BackupToolTests(unittest.TestCase):
    def run_tool(self, *args, **env):
        result = subprocess.run([sys.executable, str(ROOT / 'tools/backup_history.py'), *args],
                                env={**os.environ, **env}, capture_output=True, text=True, check=True)
        return Path(result.stdout.strip())

    def test_backup_goes_to_app_folder_not_desktop(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, app = Path(tmp) / 'sketchybar', Path(tmp) / 'app'
            (source / 'data').mkdir(parents=True)
            (source / 'sketchybarrc').write_text('bar', encoding='utf-8')
            saved = self.run_tool('--source', str(source), PERSONAL_OS_DATA_DIR=str(app), HOME=tmp)
            self.assertEqual(saved.parent, (app / 'Timer Backups').resolve())
            self.assertTrue(saved.name.startswith('before-update-'))
            manifest = json.loads((saved / 'backup-manifest.json').read_text(encoding='utf-8'))
            self.assertIn('sketchybarrc', manifest['files'])
            self.assertFalse((Path(tmp) / 'Desktop').exists())

    def test_named_destination_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'sketchybar'
            source.mkdir()
            (source / 'sketchybarrc').write_text('bar', encoding='utf-8')
            saved = self.run_tool(str(Path(tmp) / 'chosen'), '--source', str(source))
            self.assertEqual(saved, (Path(tmp) / 'chosen').resolve())


if __name__ == '__main__':
    unittest.main()
