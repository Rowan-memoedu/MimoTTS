"""Small live canaries against packaged transports; no production profiles/UI."""
import argparse
import base64
import importlib.util
import io
import json
import queue
import shutil
import struct
import subprocess
import sys
import threading
import uuid
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from mimo_tts import adapters

BUILDS = Path(r"D:\Artifacts\MimoTTS\test-builds")
parser = argparse.ArgumentParser()
parser.add_argument("--production", action="store_true")
args = parser.parse_args()
ROOT = (Path(r"D:\Artifacts\MimoTTS\production\20260927\canaries") if args.production else Path(r"D:\Artifacts\MimoTTS\adapter-checks")) / uuid.uuid4().hex[:10]
PYTHON = Path(r"D:\AppData\MimoTTS\venv\Scripts\python.exe")


def decode(path):
    result = subprocess.run([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-i", str(path), "-f", "null", "-"], capture_output=True, timeout=60)
    assert result.returncode == 0 and path.stat().st_size > 100, "Audio decode failed"


def native_canary():
    process = subprocess.Popen([PYTHON, "-u", (Path(r"D:\Projects\WebLilt\native\host.py") if args.production else BUILDS / "WebLilt" / "native" / "host.py")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    inbox = queue.Queue()

    def read():
        while header := process.stdout.read(4):
            message = json.loads(process.stdout.read(struct.unpack("<I", header)[0]))
            inbox.put(message)

    threading.Thread(target=read, daemon=True).start()

    def request(value):
        data = json.dumps(value).encode()
        process.stdin.write(struct.pack("<I", len(data)) + data)
        process.stdin.flush()
        received = []
        while True:
            event = inbox.get(timeout=120)
            assert event["id"] == value["id"]
            received.append(event)
            assert event["event"] != "error", "Native host reported an error"
            if event["event"] == "done":
                return received

    try:
        health = request({"id": "health", "op": "health"})[-1]
        assert health["engine"] == ("mimo-v2.5-tts" if args.production else "MiMo test")
        voices = request({"id": "voices", "op": "voices"})[-1]["voices"]
        assert "mimo-Mia" in [v["name"] for v in voices]
        events = request({"id": "speech", "op": "synthesize", "text": "This is an isolated browser speech test.", "voice": "mimo-Mia", "rate": 1, "pitch": 0})
        audio = b"".join(base64.b64decode(x["data"]) for x in events if x["event"] == "audio")
        target = ROOT / "weblilt.mp3"
        target.write_bytes(audio)
        decode(target)
        assert events[-1]["boundaries"] == [] and events[-1]["audioBytes"] == len(audio)
        return {"native_health": True, "voices": len(voices), "audio_bytes": len(audio), "word_timestamps": False, "browser_extension_loaded": False}
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def clipper_canary():
    output = ROOT / "clipper.mp3"
    request = {"text": "A careful comparison uses the same text.", "audio": str(output), "voice": "Mia", "rate": -3, "volume": -18, "pitch": 0, "replay": False, "play": False}
    helper = (Path(r"D:\Artifacts\MimoTTS\production\20260927\KnowledgeClipper\release") if args.production else BUILDS / "KnowledgeClipper" / "release") / "RemNoteQuickClipper.Desktop" / "Release" / "net8.0-windows" / "win-x64" / "helpers" / "stream_speech.py"
    runtime_python = Path(r"D:\Applications\RemNoteQuickClipperRuntime\edge-tts-7.2.8\Scripts\python.exe") if args.production else PYTHON
    run = subprocess.run([runtime_python, "-X", "utf8", helper, "--prepare"], input=json.dumps(request), text=True, encoding="utf-8", capture_output=True, timeout=180)
    assert run.returncode == 0, "Packaged Clipper helper failed"
    events = [json.loads(line)["event"] for line in run.stdout.splitlines()]
    assert events == ["helperReady", "firstAudioChunk", "audioComplete"], events
    decode(output)
    request["replay"] = True
    with patch.object(adapters, "synthesize", side_effect=AssertionError("Replay must never synthesize")), patch.object(sys, "stdin", io.StringIO(json.dumps(request))), patch.object(sys, "argv", ["test"]), redirect_stdout(io.StringIO()) as log:
        adapters.clipper_main()
    assert "audioComplete" not in log.getvalue()
    return {"packaged_helper_events": events, "replay_does_not_synthesize": True, "mp3_decoded": True}


def anki_canary():
    backend = adapters.AnkiBackend()
    job = ("This is an isolated flashcard audio test.", "english")
    assert backend.key(job).hash() == str(backend.key(job))
    output = Path(backend.generate(job))
    decode(output)
    with patch.object(subprocess, "run", side_effect=AssertionError("Cached audio must not synthesize")):
        assert backend.generate(job) == str(output)
    return {"backend_generate": True, "cached_replay": True, "profile_ui_verified": False}


def openfocus_canary():
    path = (Path(r"D:\Projects\OpenFocus") if args.production else BUILDS / "OpenFocus") / "openfocus" / "supervision" / "media.py"
    spec = importlib.util.spec_from_file_location("mimo_openfocus_test_media", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.Voice is adapters.OpenFocusVoice
    # No active supervision or microphone/camera access for speech comparison.
    module.Voice().close()
    return {"packaged_voice_provider": "MiMo", "speech_transport": "shared with validated Clipper PCM helper", "supervision_started": False}


def main():
    ROOT.mkdir(parents=True)
    results = {}
    for name, action in [("weblilt", native_canary), ("clipper", clipper_canary), ("anki", anki_canary), ("openfocus", openfocus_canary)]:
        print("Checking " + name, flush=True)
        try:
            results[name] = {"ok": True, **action()}
        except Exception as exc:
            results[name] = {"ok": False, "error": type(exc).__name__, "message": str(exc) if isinstance(exc, AssertionError) else "Canary failed"}
    (ROOT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"directory": str(ROOT), "results": results}))
    return 0 if all(x["ok"] for x in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
