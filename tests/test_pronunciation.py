import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mimo_tts import adapters, client


class PronunciationTests(unittest.TestCase):
    def test_sentence_boundary_wins_over_later_spaces(self):
        for sentence, tail in (
            ("Please read this complete sentence. ", "The next sentence has several more words and keeps going. " * 3),
            ("请自然地读完这个句子。", "下一句话包含 English words 和其他文字，还需要继续说明多个相关细节，最后才在这里结束。" * 4),
        ):
            with self.subTest(sentence=sentence):
                parts = client.split_text(sentence + tail, 60)
                self.assertEqual(parts[0], sentence)
                self.assertEqual("".join(parts), sentence + tail)

    def test_clause_then_space_fallback_preserves_every_character(self):
        for text in (
            "这是没有句号的长句，" + "需要保留的中文内容" * 20,
            "A meaningful clause, " + "several more ordinary words " * 15,
            "ordinary English words " * 20,
            "continuous" * 30,
        ):
            with self.subTest(text=text[:30]):
                parts = client.split_text(text, 70)
                self.assertEqual("".join(parts), text)
                self.assertTrue(all(0 < len(p) <= 70 for p in parts))
        self.assertEqual(client.split_text("这是没有句号的长句，" + "后续内容" * 30, 70)[0], "这是没有句号的长句，")

    def test_decimal_point_is_not_a_sentence_end(self):
        text = "The value is 3.14159 and the measurement continues " * 4
        parts = client.split_text(text, 50)
        self.assertTrue(all(not part.endswith("3.") for part in parts))
        self.assertEqual("".join(parts), text)

    def test_sentence_keeps_its_closing_quote(self):
        sentence = 'She said, "We will finish tomorrow." '
        text = sentence + "The following sentence continues with several more words. " * 3
        self.assertEqual(client.split_text(text, 60)[0], sentence)

    def test_style_is_separate_and_part_of_cache_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metrics = dict(first_audio_seconds=.1, total_seconds=.2, stream_events=1, finish_reason="stop")
            with patch.object(client, "CACHE", root / "cache"), patch.object(client, "_pcm", return_value=(b"\0\0" * 2400, metrics)) as provider:
                text = "Words (and parentheses) remain unchanged."
                client.synthesize(text, root / "before.wav", voice="Mia")
                client.synthesize(text, root / "guided.wav", voice="Mia", style="Natural American English.")
                cached = client.synthesize(text, root / "reused.wav", voice="Mia", style="Natural American English.")
                self.assertEqual(provider.call_count, 2)
                payload = provider.call_args.args[0]
                self.assertEqual(payload["messages"], [
                    {"role": "user", "content": "Natural American English."},
                    {"role": "assistant", "content": text},
                ])
                self.assertEqual(payload["audio"]["voice"], "Mia")
                self.assertTrue(cached["segments"][0]["cache_hit"])

    def test_clipper_forwards_style_but_old_requests_remain_compatible(self):
        for style in (None, "标准普通话，自然朗读。", "Natural American English."):
            with self.subTest(style=style), tempfile.TemporaryDirectory() as directory:
                request = dict(text="Public sample", voice="Mia", audio=str(Path(directory) / "sample.mp3"), replay=False, play=False)
                if style is not None:
                    request["style"] = style
                with patch.object(adapters.sys, "argv", ["helper"]), \
                     patch.object(adapters.sys, "stdin", io.StringIO(json.dumps(request))), \
                     patch.object(adapters, "emit"), patch.object(adapters, "synthesize") as provider:
                    adapters.clipper_main()
                    self.assertEqual(provider.call_args.kwargs["style"], style or "")
                    self.assertEqual(provider.call_args.args[0], "Public sample")
                    self.assertEqual(provider.call_args.kwargs["voice"], "Mia")


if __name__ == "__main__":
    unittest.main()
