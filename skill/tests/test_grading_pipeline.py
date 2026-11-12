"""Malformed automatic rules must be rejected by the actual build entry point."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pipeline


class GradingPipelineTests(unittest.TestCase):
    def test_invalid_rules_fail_validation_and_cannot_build(self):
        base = pipeline.read(ROOT / 'tests/fixtures/general.json')
        inventory = pipeline.read(ROOT / 'tests/fixtures/inventory.json')
        for grading in [None, [], {'kind': 'numeric', 'rationale': 'Synthetic boundary test',
                                  'rules': [{'fieldId': 'response'}]},
                        {'kind': 'numeric', 'rationale': 'Synthetic boundary test',
                         'rules': [{'fieldId': ['response'], 'expected': 7}]}]:
            with self.subTest(grading=grading), tempfile.TemporaryDirectory() as folder:
                course = copy.deepcopy(base)
                course['questions'][0]['parts'][0]['fields'][0]['kind'] = 'number'
                course['questions'][0]['grading'] = grading
                self.assertTrue(any('grading' in x for x in pipeline.validate(course, inventory)))
                output = Path(folder) / 'invalid.html'
                with self.assertRaises(ValueError):
                    pipeline.build(course, inventory, output, folder)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
