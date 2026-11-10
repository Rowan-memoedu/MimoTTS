import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mimo_tts import cli, openai_audio, router
from mimo_tts.client import MimoError


class Socket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(json.loads(value))

    def recv(self):
        return json.dumps(next(self.events))

    def close(self):
        self.closed = True


class OpenAiAudioTests(unittest.TestCase):
    def test_stream_completion_and_verbatim_validation(self):
        data = b'\0\0' * 240
        ws = Socket([{'type': 'session.updated'},
            {'type': 'response.output_audio.delta', 'delta': base64.b64encode(data).decode()},
            {'type': 'response.output_audio_transcript.done', 'transcript': 'Hello, world!'},
            {'type': 'response.done', 'response': {'status': 'completed'}}])
        chunks = []
        with patch.object(openai_audio, 'openai_key', return_value='fixture'):
            audio, metrics = openai_audio.pcm('Hello world.', on_chunk=chunks.append, connect=lambda *a, **k: ws)
        self.assertEqual(audio, data)
        self.assertEqual(chunks, [data])
        self.assertTrue(ws.closed)
        self.assertEqual(metrics['finish_reason'], 'completed')
        self.assertEqual(ws.sent[1]['response']['input'][0]['content'][0]['text'], 'Hello world.')

    def test_mismatch_and_incomplete_rejected(self):
        for status, transcript in [('completed', 'Different words'), ('incomplete', 'Hello')]:
            ws = Socket([{'type': 'session.updated'},
                {'type': 'response.output_audio.delta', 'delta': 'AAA='},
                {'type': 'response.output_audio_transcript.done', 'transcript': transcript},
                {'type': 'response.done', 'response': {'status': status}}])
            with patch.object(openai_audio, 'openai_key', return_value='fixture'), self.assertRaises(MimoError):
                openai_audio.pcm('Hello', connect=lambda *a, **k: ws)
            self.assertTrue(ws.closed)

    def test_failed_generation_has_no_target_or_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(openai_audio, 'CACHE', root / 'cache'), patch.object(openai_audio, 'pcm', side_effect=MimoError('failed')):
                with self.assertRaises(MimoError):
                    openai_audio.synthesize('Hello', root / 'output.wav')
            self.assertFalse((root / 'output.wav').exists())
            self.assertFalse(list((root / 'cache').rglob('*.wav')))

    def test_explicit_mimo_retained_and_openai_never_falls_back(self):
        with patch.object(router, 'mimo_synthesize', return_value={'provider': 'mimo'}) as old, patch.object(openai_audio, 'synthesize', side_effect=MimoError('failed')):
            self.assertEqual(router.synthesize('Hello', 'test.wav', provider='mimo')['provider'], 'mimo')
            with self.assertRaises(MimoError):
                router.synthesize('Hello', 'test.wav', provider='openai')
            self.assertEqual(old.call_count, 1)

    def test_openai_dry_run_does_not_load_credentials_or_use_mimo_request(self):
        output = io.StringIO()
        with patch.object(cli, 'selected_provider', return_value='openai'), patch.object(cli, 'openai_key', side_effect=AssertionError), patch.object(cli, 'build_request', side_effect=AssertionError), contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(['synthesize', '--text', 'Hello', '--out', 'fixture.wav', '--dry-run']), 0)
        self.assertEqual(json.loads(output.getvalue())['data']['model'], openai_audio.MODEL)


if __name__ == '__main__':
    unittest.main()
