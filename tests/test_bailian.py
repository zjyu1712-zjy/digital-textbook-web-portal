"""Provider boundaries and fail-closed responses; all network calls are simulated."""
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

from portal.config import Config
from portal.model import ModelProblem, NoRedirect, ResponsesModel


class ProviderConfigTests(unittest.TestCase):
    def test_bailian_reads_only_its_own_credentials_and_model(self):
        with patch.dict(os.environ, {
            'PORTAL_MODEL_PROVIDER': 'bailian',
            'OPENAI_API_KEY': 'openai-secret', 'OPENAI_MODEL': 'openai-model',
            'DASHSCOPE_API_KEY': 'bailian-secret', 'DASHSCOPE_MODEL': 'qwen3-vl-plus',
            'DASHSCOPE_WORKSPACE_ID': 'workspace-123',
        }, clear=True):
            config = Config.from_env()
        self.assertEqual(config.api_key, 'bailian-secret')
        self.assertEqual(config.model, 'qwen3-vl-plus')
        self.assertEqual(config.provider_label, '阿里云百炼')
        self.assertEqual(config.model_endpoint, 'https://workspace-123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions')

    def test_bailian_never_falls_back_to_openai_configuration(self):
        with patch.dict(os.environ, {'PORTAL_MODEL_PROVIDER': 'bailian',
                                     'OPENAI_API_KEY': 'openai-secret',
                                     'OPENAI_MODEL': 'openai-model'}, clear=True):
            config = Config.from_env()
        self.assertEqual(config.api_key, '')
        self.assertEqual(config.model, '')
        self.assertFalse(config.ready)
        self.assertTrue(any('业务空间' in reason for reason in config.readiness()))

    def test_openai_ignores_dashscope_credentials(self):
        with patch.dict(os.environ, {'DASHSCOPE_API_KEY': 'bailian-secret',
                                     'DASHSCOPE_MODEL': 'qwen3-vl-plus'}, clear=True):
            config = Config.from_env()
        self.assertEqual(config.api_key, '')
        self.assertEqual(config.model, '')
        self.assertEqual(config.provider_label, 'OpenAI')
        self.assertEqual(config.model_endpoint, 'https://api.openai.com/v1/responses')

    def test_unknown_provider_is_rejected(self):
        for provider in ('', 'OpenAI', 'other', 'https://proxy.invalid'):
            with self.subTest(provider=provider), patch.dict(os.environ, {'PORTAL_MODEL_PROVIDER': provider}, clear=True):
                with self.assertRaises(ValueError):
                    Config.from_env()

    def test_workspace_cannot_choose_another_origin(self):
        for workspace in ('../evil', 'x.evil.invalid', 'https://evil.invalid', 'x@evil',
                          'x:443', '-bad', 'bad-', 'a' * 64, 'a_b', 'a\n', '中文'):
            with self.subTest(workspace=workspace), patch.dict(os.environ, {
                'PORTAL_MODEL_PROVIDER': 'bailian', 'DASHSCOPE_WORKSPACE_ID': workspace,
            }, clear=True):
                with self.assertRaises(ValueError):
                    Config.from_env()

    def test_missing_workspace_blocks_readiness_and_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            (skill / 'SKILL.md').write_text('skill')
            with patch.dict(os.environ, {'PORTAL_MODEL_PROVIDER': 'bailian',
                                         'DASHSCOPE_API_KEY': 'secret',
                                         'DASHSCOPE_MODEL': 'qwen3-vl-plus',
                                         'PORTAL_SKILL_DIR': str(skill)}, clear=True):
                config = Config.from_env()
            self.assertFalse(config.ready)
            self.assertTrue(any('业务空间' in reason for reason in config.readiness()))
            with self.assertRaises(ValueError):
                _ = config.model_endpoint


class ResponseBytes(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.headers = headers or {}


def completion(content='{"ok":true}', finish='stop', **message_fields):
    return {'id': 'chatcmpl-test', 'object': 'chat.completion', 'created': 1,
            'model': 'qwen3-vl-plus', 'choices': [{'index': 0, 'finish_reason': finish,
            'message': {'role': 'assistant', 'content': content, **message_fields}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}


class ModelProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = Config(provider='bailian', bailian_workspace_id='workspace-123',
                             api_key='bailian-test-secret', model='qwen3-vl-plus')
        self.requests = []

    def transport(self, responses, headers=None):
        pending = iter(responses)
        requests = self.requests

        class Opener:
            def open(self, request, timeout):
                requests.append(request)
                payload = next(pending)
                if isinstance(payload, Exception):
                    raise payload
                return ResponseBytes(payload, headers)

        return patch('urllib.request.build_opener', return_value=Opener())

    def test_bailian_request_uses_official_beijing_host_json_and_local_image(self):
        image = self.root / 'page.png'
        image.write_bytes(b'PNG fixture')
        with self.transport([completion()]):
            result = ResponsesModel(self.config, self.root).ask('page', '教学核查', {'原文': '资料'}, [image])
        self.assertEqual(result, {'ok': True})
        req = self.requests[0]
        self.assertEqual(req.full_url, 'https://workspace-123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions')
        self.assertEqual(req.get_header('Authorization'), 'Bearer bailian-test-secret')
        body = json.loads(req.data)
        self.assertEqual(body['model'], 'qwen3-vl-plus')
        self.assertEqual(body['response_format'], {'type': 'json_object'})
        self.assertFalse(body['enable_thinking'])
        self.assertFalse(body['stream'])
        self.assertEqual(body['max_tokens'], 24000)
        self.assertNotIn('store', body)
        self.assertNotIn('tools', body)
        self.assertEqual(body['messages'][0]['role'], 'system')
        self.assertIn('JSON', body['messages'][0]['content'])
        self.assertIn('教学核查', body['messages'][0]['content'])
        self.assertEqual(body['messages'][1], {'role': 'user', 'content': [
            {'type': 'text', 'text': '{"原文": "资料"}'},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,UE5HIGZpeHR1cmU='}},
        ]})
        usage = json.loads((self.root / 'model-usage.json').read_text())
        self.assertEqual(usage['calls'], 1)
        self.assertEqual(usage['usage'][0]['tokens']['total_tokens'], 15)

    def test_missing_workspace_cannot_send_or_consume_budget(self):
        config = replace(self.config, bailian_workspace_id='')
        with self.transport([completion()]):
            with self.assertRaisesRegex(ModelProblem, '业务空间'):
                ResponsesModel(config, self.root).ask('page', 'rules', {})
        self.assertEqual(self.requests, [])
        self.assertFalse((self.root / 'model-usage.json').exists())

    def test_rejects_partialresponse_header_even_with_stop(self):
        with self.transport([completion()], {'x-dashscope-partialresponse': 'true'}):
            with self.assertRaisesRegex(ModelProblem, '完整'):
                ResponsesModel(self.config, self.root).ask('page', 'rules', {})
        self.assertEqual(list((self.root / 'model-cache').glob('*.json')), [])

    def test_rejects_truncated_filtered_tool_refusal_and_invalid_results(self):
        bad = [completion(finish='length'), completion(finish='content_filter'),
               completion(finish=None), completion(tool_calls=[{'id': 'x', 'type': 'function'}]),
               completion(refusal='cannot process'), completion(content=''),
               completion(content='{}'), completion(content='[]'), completion(content='null'),
               completion(content='```json\n{"ok":true}\n```'), completion(content='{"ok":NaN}'),
               completion(content='{"ok":'), completion(content=None), completion(content=[]),
               {'choices': []}, {'choices': [completion()['choices'][0]] * 2},
               {'choices': [None]}, {'choices': 'invalid'}, {'choices': [{'finish_reason': 'stop', 'message': []}]},
               [], None, b'not json']
        for index, response in enumerate(bad):
            with self.subTest(response=response), self.transport([response]):
                with self.assertRaises(ModelProblem):
                    ResponsesModel(self.config, self.root).ask(str(index), 'rules', {})
        self.assertEqual(list((self.root / 'model-cache').glob('*.json')), [])

    def test_cache_isolated_by_provider_workspace_and_model(self):
        variants = [self.config, replace(self.config, bailian_workspace_id='workspace-456'),
                    replace(self.config, model='another-qwen-model'),
                    replace(self.config, provider='openai', api_key='openai-test-secret')]
        openai = {'status': 'completed', 'output': [{'type': 'message', 'content': [
            {'type': 'output_text', 'text': '{"source":"openai"}'}]}]}
        with self.transport([completion('{"source":"first"}'), completion('{"source":"workspace"}'),
                             completion('{"source":"model"}'), openai]):
            for config, source in zip(variants, ('first', 'workspace', 'model', 'openai')):
                client = ResponsesModel(config, self.root)
                self.assertEqual(client.ask('same', 'rules', {}), {'source': source})
                self.assertEqual(client.ask('same', 'rules', {}), {'source': source})
        self.assertEqual(len(self.requests), 4)
        self.assertEqual(len(list((self.root / 'model-cache').glob('*.json'))), 4)
        self.assertEqual(self.requests[-1].full_url, 'https://api.openai.com/v1/responses')
        self.assertEqual(self.requests[-1].get_header('Authorization'), 'Bearer openai-test-secret')
        self.assertFalse(json.loads(self.requests[-1].data)['store'])

    def test_retry_attempts_count_toward_persistent_budget(self):
        unavailable = urllib.error.HTTPError(self.config.model_endpoint, 429, 'limited', {}, io.BytesIO())
        self.addCleanup(unavailable.close)
        with self.transport([unavailable, completion()]), patch('portal.model.time.sleep'):
            self.assertEqual(ResponsesModel(self.config, self.root).ask('page', 'rules', {}), {'ok': True})
        self.assertEqual(json.loads((self.root / 'model-usage.json').read_text())['calls'], 2)
        with self.transport([completion()]):
            with self.assertRaisesRegex(ModelProblem, '限额'):
                ResponsesModel(replace(self.config, max_model_calls=2), self.root).ask('another', 'rules', {})
        self.assertEqual(len(self.requests), 2)

    def test_bailian_opener_installs_redirect_guard(self):
        installed = []

        def make_opener(*handlers):
            installed.extend(handlers)

            class RedirectingOpener:
                def open(inner, request, timeout):
                    for handler in handlers:
                        handler.redirect_request(request, None, 302, 'redirect', {}, 'https://evil.invalid')
                    return ResponseBytes(completion())

            return RedirectingOpener()

        with patch('urllib.request.build_opener', side_effect=make_opener):
            with self.assertRaisesRegex(ModelProblem, '重定向'):
                ResponsesModel(self.config, self.root).ask('page', 'rules', {})
        self.assertTrue(any(isinstance(handler, NoRedirect) for handler in installed))
        self.assertEqual(list((self.root / 'model-cache').glob('*.json')), [])

    def test_outside_image_is_rejected_before_it_is_read(self):
        with tempfile.TemporaryDirectory() as outside:
            image = Path(outside) / 'private.png'
            image.write_bytes(b'private')
            original_read_bytes = Path.read_bytes

            def guarded_read(path):
                if path == image:
                    self.fail('An image outside the job was read before validating its path')
                return original_read_bytes(path)

            with self.transport([completion()]), patch.object(Path, 'read_bytes', guarded_read):
                with self.assertRaisesRegex(ModelProblem, '不属于本任务'):
                    ResponsesModel(self.config, self.root).ask('page', 'rules', {}, [image])
        self.assertEqual(self.requests, [])


if __name__ == '__main__':
    unittest.main()
