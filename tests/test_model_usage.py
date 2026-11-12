"""Usage-ledger tests use injected transport only; no real model request."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from unittest.mock import patch

from portal.config import Config
from portal.model import ModelProblem, ResponsesModel


def response(**extra):
    return {'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': '{"ok":true}'}]}], **extra}


class UsageLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = Config(api_key='only-test-secret', model='test-model')
        patched = patch('portal.model.skill_metadata', return_value={'fingerprint': 'a' * 64})
        patched.start(); self.addCleanup(patched.stop)

    def transport(self, values):
        pending = iter(values)
        class Opener:
            def open(inner, request, timeout):
                value = next(pending)
                if isinstance(value, BaseException):
                    raise value
                return io.BytesIO(json.dumps(value).encode())
        return patch('urllib.request.build_opener', return_value=Opener())

    def ledger(self):
        return json.loads((self.root / 'model-usage.json').read_text(encoding='utf-8'))

    def test_success_and_cache_are_distinct_without_cached_billing(self):
        with self.transport([response(usage={'input_tokens': 5, 'output_tokens': 7})]):
            client = ResponsesModel(self.config, self.root)
            client.ask('plan', 'private prompt', {'private': 'source text'})
            client.ask('plan', 'private prompt', {'private': 'source text'})
        data = self.ledger()
        self.assertEqual(data['formatVersion'], 2)
        self.assertEqual(data['calls'], 1)
        self.assertEqual([r['status'] for r in data['usage']], ['success', 'cache-hit'])
        self.assertEqual([r['attemptIndex'] for r in data['usage']], [1, None])
        self.assertIsNone(data['usage'][1]['tokens'])
        for row in data['usage']:
            self.assertEqual(row['provider'], 'openai')
            self.assertEqual(row['model'], 'test-model')
            self.assertEqual(row['skillFingerprint'], 'a' * 64)
            self.assertGreaterEqual(row['elapsedSeconds'], 0)
        encoded = json.dumps(data)
        for forbidden in ['only-test-secret', 'private prompt', 'source text']:
            self.assertNotIn(forbidden, encoded)

    def test_retries_persist_each_failed_attempt_and_known_success(self):
        error = urllib.error.HTTPError('https://api.openai.com', 429, 'secret response detail', {}, io.BytesIO())
        self.addCleanup(error.close)
        with self.transport([error, response()]), patch('portal.model.time.sleep'):
            ResponsesModel(self.config, self.root).ask('plan', 'rules', {})
        data = self.ledger()
        self.assertEqual(data['calls'], 2)
        self.assertEqual([r['status'] for r in data['usage']], ['failed', 'success'])
        self.assertEqual([r['attemptIndex'] for r in data['usage']], [1, 2])
        self.assertEqual([r['networkSequence'] for r in data['usage']], [1, 2])
        self.assertIsNone(data['usage'][0]['tokens'])
        self.assertNotIn('secret response detail', json.dumps(data))

    def test_invalid_completed_response_retains_actual_usage_as_failure(self):
        with self.transport([response(status='incomplete', usage={'input_tokens': 6, 'output_tokens': 3})]):
            with self.assertRaises(ModelProblem):
                ResponsesModel(self.config, self.root).ask('plan', 'rules', {})
        self.assertEqual(self.ledger()['usage'][0]['status'], 'failed')
        self.assertEqual(self.ledger()['usage'][0]['tokens']['input_tokens'], 6)
        self.assertEqual(list((self.root / 'model-cache').glob('*.json')), [])

    def test_connection_and_process_interruption_are_not_silently_free(self):
        with self.transport([urllib.error.URLError('secret url')]):
            with self.assertRaises(ModelProblem):
                ResponsesModel(self.config, self.root).ask('plan', 'rules', {})
        with self.transport([KeyboardInterrupt()]):
            with self.assertRaises(KeyboardInterrupt):
                ResponsesModel(self.config, self.root).ask('plan', 'rules', {})
        data = self.ledger()
        self.assertEqual(data['calls'], 2)
        self.assertEqual([r['status'] for r in data['usage']], ['failed', 'pending'])
        self.assertNotIn('secret url', json.dumps(data))
        with self.transport([response()]) as opener:
            with self.assertRaisesRegex(ModelProblem, '限额'):
                ResponsesModel(replace(self.config, max_model_calls=2), self.root).ask('new', 'rules', {})
            opener.assert_not_called()

    def test_migrate_legacy_success_without_invented_metadata_or_reset_counter(self):
        (self.root / 'model-usage.json').write_text(json.dumps({'calls': 3, 'usage': [
            {'stage': 'plan', 'tokens': {'total_tokens': 10}}]}), encoding='utf-8')
        with self.transport([response()]):
            ResponsesModel(self.config, self.root).ask('new', 'rules', {})
        data = self.ledger()
        self.assertEqual(data['calls'], 4)
        self.assertFalse(data['legacyHistoryComplete'])
        old = data['usage'][0]
        self.assertEqual(old['status'], 'success')
        for key in ('provider', 'model', 'skillFingerprint', 'elapsedSeconds', 'attemptIndex'):
            self.assertIsNone(old[key])
        self.assertEqual(data['usage'][1]['provider'], 'openai')

    def test_usage_whitelist_never_logs_provider_metadata(self):
        raw = {'usage': {'input_tokens': None, 'output_tokens': 1, 'secret': 'secret-provider-value',
                        'prompt_tokens_details': {'cached_tokens': 0, 'prompt': 'hidden'}}}
        tokens = ResponsesModel._tokens(raw)
        self.assertIsNone(tokens['input_tokens'])
        self.assertEqual(tokens['output_tokens'], 1)
        self.assertNotIn('hidden', json.dumps(tokens))
        self.assertNotIn('secret-provider-value', json.dumps(tokens))
        self.assertIsNone(ResponsesModel._tokens({}))

    def test_cache_without_ledger_cannot_silently_restart_budget(self):
        with self.transport([response()]):
            client = ResponsesModel(self.config, self.root)
            client.ask('plan', 'rules', {})
        (self.root / 'model-usage.json').unlink()
        for stage in ('plan', 'new-stage'):
            with self.transport([response()]) as opener:
                with self.assertRaisesRegex(ModelProblem, '记录缺失'):
                    client.ask(stage, 'rules', {})
                opener.assert_not_called()

    def test_v2_counter_cannot_be_smaller_than_observed_network_history(self):
        invalid = [
            {'calls': 1, 'usage': [{'status': 'success'}, {'status': 'pending'}]},
            {'calls': 1, 'usage': [{'status': 'failed', 'networkSequence': 2}]},
            {'calls': 2, 'usage': [{'status': 'success', 'networkSequence': 1}, {'status': 'failed', 'networkSequence': 1}]},
            {'calls': 2, 'usage': [{'status': 'missing'}]},
        ]
        for row in invalid:
            (self.root / 'model-usage.json').write_text(json.dumps({'formatVersion': 2, **row}), encoding='utf-8')
            with self.transport([response()]) as opener:
                with self.assertRaises(ModelProblem):
                    ResponsesModel(self.config, self.root).ask('plan', 'rules', {})
                opener.assert_not_called()

    def test_corrupt_counter_never_resets_a_job_budget(self):
        for value in [{'calls': -1, 'usage': []}, {'calls': True, 'usage': []}, {'calls': 2, 'usage': {}}]:
            (self.root / 'model-usage.json').write_text(json.dumps(value), encoding='utf-8')
            with self.transport([response()]) as opener:
                with self.assertRaises(ModelProblem):
                    ResponsesModel(self.config, self.root).ask('plan', 'rules', {})
                opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
