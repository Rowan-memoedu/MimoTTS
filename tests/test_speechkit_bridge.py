import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mimo_tts.client import MimoError
from mimo_tts.speechkit_bridge import synthesize_compatible


class BridgeTests(unittest.TestCase):
    def test_provider_failure_keeps_previous_audio_and_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "audio.mp3"
            sidecar = output.with_suffix(".mp3.words.json")
            output.write_bytes(b"previous valid audio")
            sidecar.write_text("previous timestamps")
            with patch("mimo_tts.speechkit_bridge.synthesize", side_effect=MimoError("Unavailable")):
                with self.assertRaises(MimoError):
                    synthesize_compatible(text="Hello", output=output, profile={}, voice=None,
                        speech_rate=None, instruct=None, force_refresh=False, ffprobe="ffprobe")
            self.assertEqual(output.read_bytes(), b"previous valid audio")
            self.assertEqual(sidecar.read_text(), "previous timestamps")

    def test_unsupported_clone_profile_cannot_silently_use_a_preset(self):
        with patch("mimo_tts.speechkit_bridge.synthesize") as provider:
            with self.assertRaises(MimoError):
                synthesize_compatible(text="Hello", output="audio.mp3", profile={"voice_cloning": True},
                    voice=None, speech_rate=None, instruct=None, force_refresh=False, ffprobe="ffprobe")
            provider.assert_not_called()

if __name__ == "__main__":
    unittest.main()
