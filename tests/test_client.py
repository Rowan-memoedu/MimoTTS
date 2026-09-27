import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mimo_tts import client
from mimo_tts.adapters import AnkiBackend, selected_voice


class ClientTests(unittest.TestCase):
    def test_lossless_long_text_and_whitespace(self):
        text = " \n" * 450 + ("中文括号（这个也要读）以及 English 123. \n" * 70) + " " * 1500
        parts = client.split_text(text)
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(p.strip() for p in parts))

    def test_request_roles_and_no_rewrite(self):
        request = client.build_request("原文", "design", style="青年女声", stream=False)
        self.assertEqual(request["messages"][-1], {"role": "assistant", "content": "原文"})
        self.assertIs(request["audio"]["optimize_text_preview"], False)
        self.assertNotIn("voice", request["audio"])

    def test_clone_size_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "reference.wav"
            with path.open("wb") as f:
                f.truncate(7_500_001)
            with self.assertRaises(client.MimoError):
                client.reference_url(path)

    def test_sse_fragment_parsing(self):
        stream = io.BytesIO(b': ping\n\ndata: {"choices": []}\n\ndata: [DONE]\n\n')
        self.assertEqual(list(client._sse(stream)), [{"choices": []}])

    def test_incomplete_audio_rejected(self):
        data = base64.b64encode(b"\x00\x00" * 12).decode()
        event = {"choices": [{"delta": {"audio": {"data": data}}, "finish_reason": "length"}]}
        stream = io.BytesIO(("data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n").encode())
        with patch.object(client, "_open", return_value=stream):
            with self.assertRaises(client.MimoError):
                client._pcm({"stream": True})

    def test_cache_uses_provider_and_text_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metrics = dict(first_audio_seconds=.2, total_seconds=.4, stream_events=2, finish_reason="stop")
            with patch.object(client, "CACHE", root / "cache"), patch.object(client, "_pcm", return_value=(b"\0\0" * 2400, metrics)) as provider:
                a = client.synthesize("Hello.", root / "one.wav")
                b = client.synthesize("Hello.", root / "two.wav")
                client.synthesize("Different.", root / "three.wav")
                self.assertEqual(provider.call_count, 2)
                self.assertFalse(a["segments"][0]["cache_hit"])
                self.assertTrue(b["segments"][0]["cache_hit"])
                with self.assertRaises(client.MimoError):
                    client.synthesize("Replacement", root / "one.wav")

    def test_invalid_speed_never_contacts_provider(self):
        with patch.object(client, "_open") as provider:
            with self.assertRaises(client.MimoError):
                client.synthesize("hello", "absent.wav", speed=0)
            provider.assert_not_called()

    def test_english_only_and_voice_mapping(self):
        self.assertEqual(AnkiBackend.spoken(("猫 cat 狗 dog", "english")), "cat dog")
        self.assertEqual(AnkiBackend.spoken(("猫 cat", "bilingual")), "猫 cat")
        self.assertEqual(selected_voice("hello", "en-US-AriaNeural"), "Mia")
        self.assertEqual(selected_voice("hello", "mimo-Dean"), "Dean")
        self.assertEqual(selected_voice("", "zh_female_vv_uranus_bigtts"), "Mia")


if __name__ == "__main__":
    unittest.main()
