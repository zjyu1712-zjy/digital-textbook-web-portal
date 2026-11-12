"""Run public fixtures in an external Unicode path; keep runtime evidence scoped.

This wrapper does not review content or turn screenshots into visual passes.
Browser profiles, dependency caches and private inputs are never collected.
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def under(path, parent):
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def run_acceptance(skill, previous, workspace, expected_system=None):
    skill, previous, workspace = (Path(p).resolve() for p in (skill, previous, workspace))
    if under(workspace, skill) or under(workspace, previous):
        raise ValueError('The acceptance workspace must be outside both skill directories.')
    if workspace.exists() and any(workspace.iterdir()):
        raise ValueError('Use a new or empty acceptance workspace; existing records are never overwritten.')
    workspace.mkdir(parents=True, exist_ok=True)
    artifacts, evidence, inputs, output = (workspace / name for name in ('artifacts', 'checks', 'inputs', 'output'))
    for folder in (artifacts, evidence, inputs, output):
        folder.mkdir()
    started = time.monotonic()
    report = {
        'status': 'unverified', 'testedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'platform': {'system': platform.system(), 'release': platform.release(), 'version': platform.version(),
                     'python': platform.python_version()},
        'workspaceContainsNonAscii': any(ord(c) > 127 for c in str(workspace)),
        'opening': 'file://', 'offline': True, 'stages': [], 'browserReports': {},
        'visualReview': {'status': 'unverified', 'detail': 'Screenshots are collected for separate review; this script does not inspect their pixels.'},
        'semanticReview': {'status': 'not-performed', 'detail': 'Only existing public self-authored fixtures are exercised; no new content review is claimed.'},
        'scope': 'Windows hosted runner and the recorded Playwright Chromium build only; not a cross-browser or controlled-ACL certification.',
    }
    env = os.environ.copy()
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1')
    node = env.get('NODE_BINARY') or shutil.which('node')

    def collect(path):
        path = Path(path).resolve()
        if not under(path, evidence) or path.suffix.lower() not in ('.json', '.log', '.png') or not path.is_file():
            raise ValueError('Only explicit evidence files may enter the artifact bundle: ' + str(path))
        target = artifacts / path.relative_to(evidence)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)

    def command(name, args, timeout=240):
        before = time.monotonic()
        log = evidence / 'logs' / (name + '.log')
        log.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([str(a) for a in args], cwd=workspace, env=env, capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=timeout)
        log.write_text(result.stdout + '\n' + result.stderr, encoding='utf-8')
        collect(log)
        report['stages'].append({'name': name, 'exitCode': result.returncode,
                                 'seconds': round(time.monotonic() - before, 3), 'log': 'logs/' + log.name})
        if name == 'python-unittests':
            combined = result.stdout + '\n' + result.stderr
            count = re.search(r'Ran (\d+) tests? in ', combined)
            skipped = re.search(r'OK \(skipped=(\d+)\)', combined)
            report['pythonTests'] = {'count': int(count.group(1)) if count else None,
                                     'skipped': int(skipped.group(1)) if skipped else 0,
                                     'exitCode': result.returncode}
        if result.returncode:
            raise RuntimeError(name + ' returned ' + str(result.returncode) + '; inspect the corresponding log.')
        return result.stdout

    def checked_report(path, *, doctor=False):
        result = read(path)
        collect(path)
        if doctor:
            if result.get('buildReady') is not True:
                raise RuntimeError('Environment prerequisites were not verified.')
        elif result.get('status') != 'pass' or not result.get('checks'):
            raise RuntimeError('Browser report is not a nonempty pass: ' + str(path))
        if not doctor:
            if result.get('opening') != 'file://' or result.get('remoteRequests') or result.get('errors'):
                raise RuntimeError('Offline/browser-error contract failed: ' + str(path))
            if expected_system == 'Windows' and 'Windows' not in result.get('browser', ''):
                raise RuntimeError('The browser report does not identify a Windows browser.')
            for screenshot in result.get('screenshots', []):
                collect(screenshot)
            report['browserReports'][path.parent.name] = {
                'status': result['status'], 'checks': len(result['checks']),
                'results': {state: sum(c.get('status') == state for c in result['checks'])
                            for state in sorted({c.get('status', 'unknown') for c in result['checks']})},
                'sha256': result.get('sha256'), 'browser': result.get('browser'),
                'report': str(path.relative_to(evidence)).replace(os.sep, '/'),
            }
        return result

    def pipeline(root, *args):
        return [sys.executable, root / 'scripts/pipeline.py', *args]

    def build(name, root, course, inventory, dest, incomplete=False):
        args = pipeline(root, 'build', course, '--inventory', inventory, '--out', dest, '--node', node)
        if incomplete:
            args.append('--allow-incomplete')
        command(name, args)

    try:
        if expected_system and platform.system() != expected_system:
            raise RuntimeError('Expected system ' + expected_system + ', got ' + platform.system())
        if not report['workspaceContainsNonAscii']:
            raise ValueError('The acceptance workspace must contain non-ASCII characters for the Unicode-path check.')
        if not node:
            raise ValueError('Node is required; no browser verification was run.')
        report['platform']['node'] = command('node-version', [node, '--version']).strip()
        report['skillVersion'] = read(skill / 'RELEASE.json')['version']
        report['previousSkillVersion'] = read(previous / 'RELEASE.json')['version']
        command('python-unittests', [sys.executable, '-m', 'unittest', 'discover', '-s',
                                     skill / 'tests', '-p', 'test_*.py', '-v'])
        command('doctor', [sys.executable, skill / 'scripts/doctor.py', '--workspace', workspace,
                           '--node', node, '--out', evidence / 'environment.json'])
        checked_report(evidence / 'environment.json', doctor=True)

        # Browser evidence is renderer-specific. Do not renew old evidence merely
        # because a new build is required for a test. Preserve content and reviews.
        demo = read(skill / 'examples/demo-course.json')
        removed = len(demo.pop('chapterChecks', []))
        demo_file = inputs / '自编示例.json'
        write(demo_file, demo)
        report['fixturePreparation'] = {'removedOldChapterChecks': removed,
                                        'newReviewRecordsWritten': 0,
                                        'reason': 'Runtime-only fixture: do not reuse old renderer validation.'}
        demo_inventory = skill / 'examples/demo-inventory.json'
        validation = evidence / 'demo-validation.json'
        command('validate-demo', pipeline(skill, 'validate', demo_file, '--inventory', demo_inventory, '--out', validation))
        collect(validation)
        if read(validation).get('errors'):
            raise RuntimeError('Demo validation contains errors despite a successful process.')
        demo_html = output / '自编示例.html'
        build('build-demo', skill, demo_file, demo_inventory, demo_html)
        inspected = command('inspect-demo', pipeline(skill, 'inspect', demo_html))
        if json.loads(inspected) != []:
            raise RuntimeError('The generated HTML has external resource problems.')
        report['demoSHA256'] = hashlib.sha256(demo_html.read_bytes()).hexdigest()

        for script, name in [('runtime-check.cjs', 'runtime'), ('demo.cjs', 'demo'),
                             ('mistakes-ui.cjs', 'mistakes'), ('quality-ui.cjs', 'quality')]:
            result_file = evidence / name / 'report.json'
            destination = result_file if name == 'runtime' else result_file.parent
            try:
                command(name, [node, skill / 'tests' / script, demo_html, destination])
            finally:
                if result_file.exists():
                    collect(result_file)
            checked_report(result_file)

        partial_dir = inputs / 'partial-fixture'
        command('build-partial', [sys.executable, skill / 'tests/make_partial.py', partial_dir])
        partial_report = evidence / 'ranges/report.json'
        command('ranges', [node, skill / 'tests/learning-range-ui.cjs', partial_dir / 'partial.html', partial_report.parent])
        checked_report(partial_report)

        # The baseline really uses the previous implementation. Replacing bytes
        # at the same file URL exercises existing drafts and immutable attempts.
        general = skill / 'tests/fixtures/general.json'
        general_inventory = skill / 'tests/fixtures/inventory.json'
        fusion = skill / 'tests/fixtures/fusion.json'
        fusion_inventory = skill / 'tests/fixtures/fusion-inventory.json'
        old_html, current_html, stale_html, legacy_html = (output / name for name in
            ('旧版.html', '新版.html', '内容变化.html', '未绑定旧内容.html'))
        build('build-previous', previous, previous / 'tests/fixtures/general.json',
              previous / 'tests/fixtures/inventory.json', old_html)
        build('build-current', skill, fusion, fusion_inventory, current_html)
        stale = copy.deepcopy(read(fusion))
        stale['chapters'][0]['sections'][0]['blocks'][0]['text'] += '（自编测试：此处新增内容尚未复核。）'
        stale_file = inputs / '需复核.json'
        write(stale_file, stale)
        build('build-stale', skill, stale_file, fusion_inventory, stale_html, incomplete=True)
        build('build-legacy', skill, general, general_inventory, legacy_html)
        migration = evidence / 'migration/report.json'
        try:
            command('migration', [node, skill / 'tests/assurance.cjs', old_html, current_html,
                                  stale_html, legacy_html, migration])
        finally:
            if migration.exists():
                collect(migration)
        checked_report(migration)
        report['status'] = 'pass'
    except Exception as exc:
        report['status'] = 'fail'
        report['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        report['durationSeconds'] = round(time.monotonic() - started, 3)
        write(artifacts / 'summary.json', report)
        print(json.dumps({'status': report['status'], 'system': report['platform']['system'],
                          'report': str(artifacts / 'summary.json'), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['status'] == 'pass' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill', required=True, type=Path)
    parser.add_argument('--previous-skill', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--expected-system', help='CI sets Windows; local rehearsals must not pretend to be Windows.')
    args = parser.parse_args()
    try:
        return run_acceptance(args.skill, args.previous_skill, args.workspace, args.expected_system)
    except (OSError, ValueError) as exc:
        print(json.dumps({'status': 'fail', 'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
