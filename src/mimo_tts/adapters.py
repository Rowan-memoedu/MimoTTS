"""Shared MiMo speech transports used by installed applications and test builds."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .client import ARTIFACTS, MimoError, VOICES, default_voice, synthesize

PYTHON = Path(r"D:\AppData\MimoTTS\venv\Scripts\python.exe")
FFMPEG_BIN = Path(r"D:\Applications\P47\FFmpeg\ffmpeg-8.1.2-full_build\bin")


def runtime_environment():
    # Desktop launchers may still carry an old PATH and embedded Python settings.
    environment = dict(os.environ)
    environment.pop("PYTHONHOME", None)
    environment.pop("PYTHONPATH", None)
    if FFMPEG_BIN.is_dir():
        environment["PATH"] = str(FFMPEG_BIN) + os.pathsep + environment.get("PATH", "")
    return environment


def selected_voice(text, old_voice=""):
    if old_voice in VOICES:
        return old_voice
    if old_voice.startswith("mimo-") and old_voice[5:] in VOICES:
        return old_voice[5:]
    return default_voice(text)


def emit(name, **extra):
    print(json.dumps({"event": name, "at": datetime.now(timezone.utc).isoformat(), **extra}), flush=True)


def clipper_main():
    if "--prepare" in sys.argv:
        emit("helperReady")
    request = json.load(sys.stdin)
    audio = Path(request["audio"])
    rate, volume = 1 + request.get("rate", 0) / 100, 1 + request.get("volume", 0) / 100
    if request.get("pitch", 0):
        raise MimoError("MiMo requires pitch=0; Hz pitch shifting is not provided.")
    replay = bool(request["replay"])
    player = None
    if request.get("play", True):
        input_format = ["-f", "mp3"] if replay else ["-f", "s16le", "-ar", "24000", "-ch_layout", "mono"]
        command = [request["ffplay"], "-nodisp", "-autoexit", "-loglevel", "error", *input_format, "-i", "pipe:0"]
        if not replay:
            command += ["-af", f"atempo={rate},volume={volume}"]
        player = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        emit("playerStarted", pid=player.pid)
    first = True

    def chunk(data):
        nonlocal first
        if first:
            emit("firstAudioChunk")
            first = False
        if player:
            player.stdin.write(data)
            player.stdin.flush()

    try:
        if replay:
            with audio.open("rb") as saved:
                while data := saved.read(16384):
                    if player:
                        player.stdin.write(data)
            # Replay deliberately does not emit audioComplete or invoke the API.
        else:
            synthesize(request["text"], audio, voice=selected_voice(request["text"], request["voice"]), style=request.get("style", ""), on_chunk=chunk, speed=rate, volume=volume)
            emit("audioComplete")
        if player:
            player.stdin.close()
            player.stderr.read()
            if player.wait(timeout=600):
                raise MimoError("Audio player could not complete playback.")
            emit("playbackComplete")
    finally:
        if player and player.poll() is None:
            player.kill()
            player.wait()
        if player and not player.stdin.closed:
            try:
                player.stdin.close()
            except OSError:
                pass


async def weblilt_synthesize(request, send):
    text = request.get("text", "")
    if not isinstance(text, str) or not text.strip() or len(text) > 1200:
        raise ValueError("Text must contain 1-1200 characters")
    if request.get("pitch", 0):
        raise ValueError("MiMo supports pitch=0 only")
    speed = float(request.get("rate", 1))
    if not .5 <= speed <= 2.5:
        raise ValueError("Rate is outside supported range")
    root = ARTIFACTS / "runtime" / "weblilt"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as directory:
        output = Path(directory) / "audio.mp3"
        command = [str(PYTHON), "-X", "utf8", "-m", "mimo_tts.cli", "--json", "synthesize", "--text-file", "-", "--out", str(output), "--voice", selected_voice(text, request.get("voice", "")), "--speed", str(speed)]
        process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            result, _ = await process.communicate(text.encode("utf-8"))
            if process.returncode:
                raise RuntimeError("MiMo synthesis failed; inspect CLI doctor")
            data = output.read_bytes()
            if not data or len(data) > 8 * 1024 * 1024:
                raise ValueError("Generated audio is empty or exceeds 8 MB")
            import base64
            for offset in range(0, len(data), 96 * 1024):
                send({"event": "audio", "data": base64.b64encode(data[offset:offset + 96 * 1024]).decode("ascii")})
            send({"event": "done", "boundaries": [], "audioBytes": len(data), "provider": "mimo", "wordTimestamps": False})
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


class AnkiBackend:
    """Same Backend protocol as SuperFreeTTSReview, with a separate MiMo cache."""
    def __init__(self, upstream=None):
        self.root = Path(r"D:\Caches\MimoTTS\anki")
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def spoken(job):
        text, mode = job
        # MiMo is multilingual; English-only must filter Han explicitly.
        return re.sub(r"\s+", " ", re.sub(r"[\u3400-\u9fff]", " ", text)).strip() if mode == "english" else text

    def key(self, job):
        class RequestKey(str):
            def hash(self):
                return str(self)
        return RequestKey(hashlib.sha256(json.dumps({"schema": 2, "provider": "mimo-v2.5-tts", "voice": "Mia", "text": self.spoken(job), "mode": job[1]}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest())

    def cached(self, job):
        path = self.root / (self.key(job) + ".mp3")
        return str(path) if path.exists() and path.stat().st_size else None

    def generate(self, job):
        existing = self.cached(job)
        if existing:
            return existing
        target = self.root / (self.key(job) + ".mp3")
        voice = "Mia"
        # Anki's embedded Python does not need the package or networking dependencies.
        command = [str(PYTHON), "-I", "-X", "utf8", "-m", "mimo_tts.cli", "--json", "synthesize", "--text-file", "-", "--voice", voice, "--out", str(target)]
        result = subprocess.run(command, input=self.spoken(job), text=True, encoding="utf-8", capture_output=True, timeout=600, env=runtime_environment(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode:
            raise RuntimeError("MiMo synthesis failed; check mimo-tts doctor")
        return str(target)


class OpenFocusVoice:
    def __init__(self):
        self.process = None

    def speak(self, text):
        if self.process is not None and self.process.poll() is None:
            return
        self.process = subprocess.Popen([str(PYTHON), "-X", "utf8", "-m", "mimo_tts.adapters", "openfocus"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.process.stdin.write(text.encode("utf-8"))
        self.process.stdin.close()

    def close(self):
        if self.process is not None and self.process.poll() is None:
            # Kill the player child as well as synthesis, preserving the old stop behavior.
            subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.process.wait()


def main():
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "openfocus":
            text = sys.stdin.read()
            directory = ARTIFACTS / "runtime" / "openfocus"
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(dir=directory) as temp:
                request = {"text": text, "voice": default_voice(text), "rate": 0, "volume": 0, "pitch": 0, "ffplay": shutil.which("ffplay"), "audio": str(Path(temp) / "voice.mp3"), "replay": False, "play": True}
                sys.stdin = __import__("io").StringIO(json.dumps(request))
                clipper_main()
        else:
            clipper_main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, MimoError) else type(exc).__name__ + ": MiMo audio failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
