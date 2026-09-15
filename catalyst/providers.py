"""Local API adapters. Fixed HTTPS hosts, bounded output, no tools or paid fallback.

Reviewed interfaces: OpenAI Responses API and Anthropic Messages API, 2026-09-15.
No subscription authentication, account discovery, or credential forwarding.
"""
from dataclasses import dataclass
import json
import re
import time
import httpx

HOSTS = {'openai': 'https://api.openai.com', 'anthropic': 'https://api.anthropic.com'}
MESSAGES = {
    'key': 'Use a provider API key. Subscription passwords, cookies, and session tokens are not supported.',
    'auth': 'The provider rejected this API key. Check its project and permissions.',
    'quota': 'The provider reported a rate limit or unavailable API credit. No retry or paid fallback was started.',
    'model': 'The provider could not run this request. Choose a supported text model and check its API access.',
    'network': 'The provider connection failed or timed out. Check connectivity before retrying.',
    'response': 'The provider did not return a complete text response. No partial result was submitted.',
    'cancelled': 'This run was stopped. No further provider request will start.',
    'limit': 'The response exceeded this connector’s size or time limit. No partial result was submitted.',
    'context': 'This assignment exceeds the connector’s context limit. Narrow the investigation before trying again.',
}


class ProviderFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


@dataclass
class ModelResult:
    text: str
    model: str
    response_id: str


class ProviderClient:
    def __init__(self, provider, key, transport=None):
        prefix = 'sk-ant-' if provider == 'anthropic' else 'sk-'
        if provider not in HOSTS or not key.startswith(prefix) or not re.fullmatch(r'[A-Za-z0-9_-]{12,1024}', key):
            raise ProviderFailure('key')
        self.provider = provider
        self.key = key
        headers = {'Authorization': 'Bearer ' + key} if provider == 'openai' else {'x-api-key': key, 'anthropic-version': '2023-06-01'}
        self.client = httpx.Client(base_url=HOSTS[provider], headers=headers, timeout=httpx.Timeout(30, connect=10),
                                   follow_redirects=False, trust_env=False, transport=transport)

    def close(self):
        self.client.close()
        self.client.headers.clear()
        self.key = ''

    def check(self, response):
        if response.status_code in (401, 403):
            raise ProviderFailure('auth')
        if response.status_code in (402, 429):
            raise ProviderFailure('quota')
        if not response.is_success:
            raise ProviderFailure('model' if response.status_code < 500 else 'network')

    def models(self):
        try:
            response = self.client.get('/v1/models')
            self.check(response)
            if len(response.content) > 1_000_000:
                raise ProviderFailure('response')
            rows = response.json().get('data', [])
            models = [r['id'] for r in rows if isinstance(r, dict) and isinstance(r.get('id'), str)
                      and re.fullmatch(r'[A-Za-z0-9._:/-]{1,120}', r['id'])]
            if self.provider == 'openai':
                models = [m for m in models if m.startswith(('gpt-', 'o1', 'o3', 'o4')) and not any(x in m for x in ('audio','realtime','transcrib','tts','image','search','deep-research','codex'))]
                models = sorted(set(models), key=lambda m: (m != 'gpt-4.1-mini', m))
            else:
                models = sorted(set(models), key=lambda m: ('haiku' not in m, m))
            if not models:
                raise ProviderFailure('model')
            return models[:200]
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise ProviderFailure('network' if isinstance(exc, httpx.HTTPError) else 'response') from None

    def generate(self, model, instructions, prompt, max_tokens=1200, on_text=None, cancelled=lambda: False):
        if len(prompt) > 32000:
            raise ProviderFailure('context')
        if cancelled():
            raise ProviderFailure('cancelled')
        if self.provider == 'openai':
            path = '/v1/responses'
            body = {'model': model, 'instructions': instructions, 'input': prompt, 'max_output_tokens': max_tokens,
                    'stream': True, 'store': False, 'tools': []}
        else:
            path = '/v1/messages'
            body = {'model': model, 'system': instructions, 'messages': [{'role': 'user', 'content': prompt}],
                    'max_tokens': max_tokens, 'stream': True}
        output, actual_model, response_id, complete, stopped = '', '', '', False, False
        started, byte_count = time.monotonic(), 0
        try:
            with self.client.stream('POST', path, json=body) as response:
                self.check(response)
                for line in response.iter_lines():
                    if cancelled():
                        raise ProviderFailure('cancelled')
                    byte_count += len(line)
                    if byte_count > 1_000_000 or len(line) > 100_000 or time.monotonic()-started > 210:
                        raise ProviderFailure('limit')
                    if not line.startswith('data:') or line[5:].strip() == '[DONE]':
                        continue
                    event = json.loads(line[5:])
                    kind = event.get('type')
                    if kind in ('error', 'response.failed', 'response.incomplete'):
                        raise ProviderFailure('response')
                    delta = ''
                    if self.provider == 'openai':
                        if kind == 'response.output_text.delta':
                            delta = event.get('delta', '')
                        elif kind == 'response.completed':
                            record = event.get('response', {})
                            if record.get('status') != 'completed':
                                raise ProviderFailure('response')
                            actual_model, response_id = record.get('model', ''), record.get('id', '')
                            complete = True
                    else:
                        if kind == 'message_start':
                            record = event.get('message', {})
                            actual_model, response_id = record.get('model', ''), record.get('id', '')
                        elif kind == 'content_block_delta' and event.get('delta', {}).get('type') == 'text_delta':
                            delta = event['delta'].get('text', '')
                        elif kind == 'message_delta':
                            stopped = event.get('delta', {}).get('stop_reason') == 'end_turn'
                        elif kind == 'message_stop':
                            complete = stopped
                    # Only visible response text is retained. Reasoning events are ignored.
                    if not isinstance(delta, str):
                        raise ProviderFailure('response')
                    output += delta
                    if len(output) > 6000:
                        raise ProviderFailure('limit')
                    if self.key and self.key in output:
                        raise ProviderFailure('response')
                    if delta and on_text:
                        # Withhold any trailing fragment that might grow into the known key.
                        suffix = next((n for n in range(min(len(output),len(self.key)-1),0,-1) if output.endswith(self.key[:n])),0)
                        on_text(output[:-suffix] if suffix else output)
            if cancelled():
                raise ProviderFailure('cancelled')
            if not complete or not output.strip() or not actual_model or not response_id:
                raise ProviderFailure('response')
            if (not isinstance(actual_model,str) or not re.fullmatch(r'[A-Za-z0-9._:/-]{1,120}', actual_model)
                    or not isinstance(response_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', response_id)
                    or (self.key and self.key in (actual_model+' '+response_id))):
                raise ProviderFailure('response')
            return ModelResult(output.strip(), actual_model, response_id)
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise ProviderFailure('network' if isinstance(exc, httpx.HTTPError) else 'response') from None
