"""Exercise the real CLI outside its installation, including a non-UTF-8 locale."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'pipeline.py'


class PortabilityTests(unittest.TestCase):
    def test_external_workspace_keeps_unicode_in_ascii_locale(self):
        with tempfile.TemporaryDirectory(prefix='textbook-work space-') as tmp:
            work = Path(tmp)
            course = json.loads((ROOT / 'tests/fixtures/general.json').read_bytes())
            course['title'] = '中文教材 · Δ 🧮'
            (work / 'course.json').write_bytes(json.dumps(course, ensure_ascii=False).encode('utf-8'))
            env = {**os.environ, 'LC_ALL': 'C', 'PYTHONUTF8': '0', 'PYTHONCOERCECLOCALE': '0',
                   'PYTHONIOENCODING': 'ascii', 'PYTHONDONTWRITEBYTECODE': '1'}
            command = [sys.executable, str(SCRIPT), 'build', 'course.json', '--inventory',
                       str(ROOT / 'tests/fixtures/inventory.json'), '--assets', '.', '--out', 'output/book.html']
            result = subprocess.run(command, cwd=work, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
            self.assertIn('中文教材 · Δ 🧮', (work / 'output/book.html').read_text(encoding='utf-8'))
            self.assertEqual(json.loads(result.stdout)['structuralErrors'], [])
            inspected = subprocess.run([sys.executable, str(SCRIPT), 'inspect', 'output/book.html'],
                                       cwd=work, env=env, capture_output=True)
            self.assertEqual(inspected.returncode, 0, inspected.stderr.decode('utf-8', errors='replace'))
            self.assertEqual(json.loads(inspected.stdout), [])


if __name__ == '__main__':
    unittest.main()
