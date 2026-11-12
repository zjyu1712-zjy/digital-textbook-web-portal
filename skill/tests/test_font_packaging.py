"""Verify actual offline font bytes, without losing a font or repeating fallbacks."""
import base64
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pipeline


class FontPackagingTests(unittest.TestCase):
    def test_every_bundled_font_embedded_once_and_byte_identical(self):
        fixture = ROOT / 'tests/fixtures'
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'demo.html'
            pipeline.build(pipeline.read(fixture / 'general.json'),
                           pipeline.read(fixture / 'inventory.json'), target, folder)
            html = target.read_text(encoding='utf-8')
            fonts = re.findall(r'data:font/woff2;base64,([A-Za-z0-9+/=]+)', html)
            expected = {p.read_bytes() for p in (ROOT / 'assets/vendor').glob('*.woff2')}
            self.assertEqual({base64.b64decode(s) for s in fonts}, expected)
            self.assertEqual(len(fonts), len(expected), 'duplicate format fallbacks inflate HTML')
            self.assertEqual(pipeline.inspect_html(target), [])
            self.assertLess(sum(map(len, fonts)), 400000)


if __name__ == '__main__':
    unittest.main()
