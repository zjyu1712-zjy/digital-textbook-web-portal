"""CLI boundary regressions; no browser is launched by these tests.

Optional launch-failure coverage uses PLAYWRIGHT_MODULE (or a normal installation)
with a deliberately nonexistent browser executable. It skips without Playwright.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('runtime-check.cjs')
NODE = os.environ.get('NODE_BINARY') or shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is not available')
class RuntimeContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dth-runtime-contract-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.html = self.root / 'fixture.html'
        self.html.write_text('<!doctype html><title>Contract test only</title>', encoding='utf-8')
        self.output = self.root / 'report.json'

    def run_check(self, module=None, *, preload=None, browser=None):
        env = os.environ.copy()
        if module is None:
            env.pop('PLAYWRIGHT_MODULE', None)
        else:
            env['PLAYWRIGHT_MODULE'] = str(module)
        if browser:
            env['BROWSER_EXECUTABLE'] = str(browser)
        else:
            env.pop('BROWSER_EXECUTABLE', None)
        command = [NODE]
        if preload:
            command.extend(['--require', str(preload)])
        command.extend([str(SCRIPT), str(self.html), str(self.output)])
        result = subprocess.run(command, cwd=self.root, env=env, capture_output=True,
                                text=True, timeout=30)
        self.assertTrue(self.output.is_file(), 'runtime-check must retain a JSON report: ' + result.stderr)
        return result, json.loads(self.output.read_text(encoding='utf-8'))

    def assert_unverified(self, result, report):
        self.assertEqual(report['status'], 'unverified')
        self.assertEqual(report['checks'], [])
        self.assertNotEqual(result.returncode, 0, 'an unverified run must not look successful to a CLI caller')

    def test_missing_playwright_reports_unverified_with_nonzero_exit(self):
        result, report = self.run_check(self.root / 'does-not-exist' / 'playwright.cjs')
        self.assert_unverified(result, report)
        self.assertIn('Playwright', report['detail'])

    def test_workspace_only_playwright_resolves_without_installation_writes(self):
        package = self.root / 'node_modules' / 'playwright'
        package.mkdir(parents=True)
        package.joinpath('index.js').write_text(
            "module.exports={chromium:{launchPersistentContext:async()=>{"
            "throw new Error('workspace-only-package: browser deliberately disabled');}}};",
            encoding='utf-8')
        for requested in (None, 'playwright'):
            with self.subTest(requested=requested):
                result, report = self.run_check(requested)
                self.assert_unverified(result, report)
                self.assertIn('workspace-only-package: browser deliberately disabled', report['detail'])

    def test_empty_screenshots_do_not_claim_screenshots_were_provided(self):
        _, report = self.run_check(self.root / 'missing-playwright.cjs')
        self.assertEqual(report['screenshots'], [])
        self.assertEqual(report['visualReview']['status'], 'unverified')
        self.assertNotIn('截图已提供', report['visualReview']['detail'])

    def test_node_below_20_is_reported_before_playwright_import(self):
        preload = self.root / 'old-node.cjs'
        preload.write_text("Object.defineProperty(process.versions, 'node', {value:'18.19.0'});", encoding='utf-8')
        marker = self.root / 'imported.txt'
        dependency = self.root / 'exits-on-import.cjs'
        dependency.write_text("require('node:fs').writeFileSync(" + json.dumps(str(marker)) +
                              ", 'loaded'); process.exit(33);", encoding='utf-8')
        result, report = self.run_check(dependency, preload=preload)
        self.assert_unverified(result, report)
        self.assertIn('Node.js', report['detail'])
        self.assertIn('20', report['detail'])
        self.assertFalse(marker.exists(), 'unsupported Node must be rejected before importing Playwright')

    def test_playwright_import_process_exit_still_retains_unverified_report(self):
        dependency = self.root / 'exit-zero-on-import.cjs'
        dependency.write_text('process.exit(0);', encoding='utf-8')
        result, report = self.run_check(dependency)
        self.assert_unverified(result, report)
        self.assertIn('Playwright', report['detail'])

    def test_browser_launch_failure_reports_unverified_with_nonzero_exit(self):
        probe = subprocess.run([NODE, '-e',
            "const p=require(process.env.PLAYWRIGHT_MODULE||'playwright');"
            "if(!p.chromium)process.exit(1);console.log(require.resolve(process.env.PLAYWRIGHT_MODULE||'playwright'));"],
            cwd=SCRIPT.parent, env=os.environ.copy(), capture_output=True, text=True, timeout=20)
        if probe.returncode:
            self.skipTest('Playwright is unavailable; launch-failure integration is optional')
        module = probe.stdout.strip().splitlines()[-1]
        result, report = self.run_check(module, browser=self.root / 'nonexistent-browser')
        self.assert_unverified(result, report)
        self.assertIn('无法启动', report['detail'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
