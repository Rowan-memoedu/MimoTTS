import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mimo_tts import adapters


class Player:
    def __init__(self, command, **kwargs):
        self.command = command
        self.stdin = io.BytesIO()
        self.stderr = io.BytesIO()
        self.pid = 123
        self.data = None
        close = self.stdin.close
        def capture():
            self.data = self.stdin.getvalue()
            close()
        self.stdin.close = capture

    def wait(self, **kwargs):
        return 0

    def poll(self):
        return 0


class ClipperReplayTests(unittest.TestCase):
    def run_request(self, request, provider):
        players = []
        def create(command, **kwargs):
            player = Player(command, **kwargs)
            players.append(player)
            return player
        with patch.object(adapters.sys, "stdin", io.StringIO(json.dumps(request))), \
             patch.object(adapters.sys, "argv", ["helper"]), \
             patch.object(adapters, "synthesize", provider), \
             patch.object(adapters.subprocess, "Popen", create), \
             patch.object(adapters, "emit"):
            adapters.clipper_main()
        return players[0]

    def test_first_and_replay_use_identical_pcm_and_filters(self):
        # Two voices/settings and uneven network chunks exercise the transport,
        # without external TTS calls or output to the user's audio device.
        for voice, rate, volume in (("Mia", -3, -18), ("Dylan", 25, 10)):
            with self.subTest(voice=voice), tempfile.TemporaryDirectory(dir=r"D:\Caches") as root:
                audio = Path(root) / "temporary.mp3"
                pcm = bytes(range(256)) * 37
                def synth(text, out, **kwargs):
                    kwargs["on_chunk"](pcm[:174])
                    kwargs["on_chunk"](pcm[174:])
                    out.write_bytes(b"ID3 lossy export")
                request = dict(text="Public audio fixture", voice=voice, rate=rate, volume=volume,
                               pitch=0, ffplay="fake-player", audio=str(audio), replay=False,
                               play=True, losslessReplay=True)
                first = self.run_request(request, synth)
                # Production renames the final MP3 and its sidecar together.
                cached = audio.with_name("cached.mp3")
                audio.rename(cached)
                sidecar = Path(str(audio) + ".pcm")
                if sidecar.exists():
                    sidecar.rename(str(cached) + ".pcm")
                replay = self.run_request({**request, "audio": str(cached), "replay": True,
                                           "rate": rate + 10, "volume": volume + 5},
                                          lambda *a, **kw: self.fail("replay must not synthesize"))
                self.assertEqual(first.data, pcm)
                self.assertEqual(replay.data, first.data)
                self.assertEqual(replay.command, first.command)

    def test_legacy_mp3_replay_never_synthesizes_or_applies_filters_twice(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Caches") as root:
            audio = Path(root) / "old.mp3"
            audio.write_bytes(b"ID3 old recording")
            player = self.run_request(dict(audio=str(audio), replay=True, play=True,
                losslessReplay=True, rate=-3, volume=-18, ffplay="fake-player"),
                lambda *a, **kw: self.fail("legacy replay must not synthesize"))
            self.assertEqual(player.data, audio.read_bytes())
            self.assertNotIn("-af", player.command)

    def test_corrupt_sidecar_fails_without_regeneration(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Caches") as root:
            audio = Path(root) / "fixture.mp3"
            audio.write_bytes(b"ID3 fixture")
            Path(str(audio) + ".pcm").write_bytes(b"broken sidecar")
            with self.assertRaises(adapters.MimoError):
                self.run_request(dict(audio=str(audio), replay=True, play=True,
                    losslessReplay=True, rate=0, volume=0, ffplay="fake-player"),
                    lambda *a, **kw: self.fail("corrupt replay must not synthesize"))

    def test_existing_apps_without_opt_in_keep_their_transport(self):
        with tempfile.TemporaryDirectory(dir=r"D:\Caches") as root:
            audio = Path(root) / "legacy-request.mp3"
            def synth(text, out, **kwargs):
                kwargs["on_chunk"](b"\x00\x01" * 30)
                out.write_bytes(b"ID3 existing transport")
            request = dict(text="Public fixture", voice="Mia", rate=0, volume=0,
                           ffplay="fake-player", audio=str(audio), replay=False, play=True)
            first = self.run_request(request, synth)
            replay = self.run_request({**request, "replay": True},
                                      lambda *a, **kw: self.fail("legacy replay must not synthesize"))
            self.assertFalse(Path(str(audio) + ".pcm").exists())
            self.assertIn("s16le", first.command)
            self.assertIn("mp3", replay.command)
            self.assertEqual(replay.data, audio.read_bytes())


if __name__ == "__main__":
    unittest.main()
