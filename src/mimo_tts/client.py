from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

BASE_URL = "https://api.xiaomimimo.com/v1"
MODELS = {"preset": "mimo-v2.5-tts", "design": "mimo-v2.5-tts-voicedesign", "clone": "mimo-v2.5-tts-voiceclone"}
VOICES = ("冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean")
CACHE = Path(r"D:\Caches\MimoTTS")
ARTIFACTS = Path(r"D:\Artifacts\MimoTTS")
SAMPLE_RATE = 24000


class MimoError(RuntimeError):
    """Messages must not contain provider bodies, credentials or source text."""


def credential():
    value = os.environ.get("MIMO_API_KEY", "").strip()
    if value:
        return value, "process-environment"
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value = str(winreg.QueryValueEx(key, "MIMO_API_KEY")[0]).strip()
            if value:
                return value, "windows-user-environment"
        except (OSError, ValueError):
            pass
    raise MimoError("MIMO_API_KEY is missing; set the Windows user environment variable.")


def voices():
    return [{"id": name, "language": "zh" if i < 4 else "en", "gender": "female" if i % 4 < 2 else "male"} for i, name in enumerate(VOICES)]


def default_voice(text):
    return "Mia"


def split_text(text, limit=400):
    if not isinstance(text, str) or not text.strip():
        raise MimoError("Text must not be empty.")
    if len(text) > 100_000:
        raise MimoError("Text exceeds the 100000 character per-job bound.")
    if not 50 <= limit <= 1000:
        raise MimoError("Chunk size must be between 50 and 1000 characters.")
    parts = []
    while len(text) > limit:
        candidates = list(re.finditer(r"[。！？.!?；;\n]\s*|\s+", text[:limit]))
        end = candidates[-1].end() if candidates and candidates[-1].end() >= limit // 3 else limit
        parts.append(text[:end])
        text = text[end:]
    if text:
        parts.append(text)
    # Preserve every character; whitespace-only pieces merge into a neighbor.
    merged = []
    for part in parts:
        if not part.strip() and merged:
            merged[-1] += part
        else:
            merged.append(part)
    if len(merged) > 1 and not merged[0].strip():
        merged[1] = merged[0] + merged[1]
        merged.pop(0)
    return merged


def reference_url(path):
    path = Path(path)
    if path.suffix.lower() not in (".mp3", ".wav"):
        raise MimoError("Reference audio must be WAV or MP3.")
    if path.stat().st_size > 7_500_000:
        raise MimoError("Reference audio is too large (base64 must not exceed 10 MB).")
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    if len(encoded) > 10_000_000:
        raise MimoError("Base64 reference exceeds 10 MB.")
    mime = "audio/wav" if path.suffix.lower() == ".wav" else "audio/mpeg"
    return f"data:{mime};base64,{encoded}", hashlib.sha256(data).hexdigest()


def build_request(text, mode="preset", voice=None, style="", reference=None, stream=True):
    if mode not in MODELS:
        raise MimoError("Unknown mode; choose preset, design or clone.")
    if not text.strip():
        raise MimoError("Text must not be empty.")
    if len(style) > 1024:
        raise MimoError("Style description exceeds 1024 characters.")
    audio = {"format": "pcm16" if stream else "wav"}
    if mode == "preset":
        voice = voice or default_voice(text)
        if voice not in VOICES:
            raise MimoError("Unknown preset voice; run mimo-tts voices.")
        audio["voice"] = voice
    elif mode == "design":
        if not style.strip():
            raise MimoError("Voice design requires --style.")
        # The official demo enables rewriting. Reader integrations must preserve text.
        audio["optimize_text_preview"] = False
    else:
        if not reference:
            raise MimoError("Voice cloning requires --reference WAV/MP3.")
        audio["voice"] = reference_url(reference)[0]
    messages = ([{"role": "user", "content": style}] if style else [])
    messages.append({"role": "assistant", "content": text})
    return {"model": MODELS[mode], "messages": messages, "audio": audio, "stream": stream}


def _open(payload=None, path="/chat/completions"):
    key, _ = credential()
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(BASE_URL + path, data=data, headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    # Only retry opening a response. Never duplicate a stream after emitting audio.
    for attempt in range(3):
        try:
            return urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as exc:
            code = exc.code
            retry = exc.headers.get("Retry-After", "")
            exc.close()
            if code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(min(float(retry), 10) if retry.isdigit() else 1 + attempt * 2)
                continue
            raise MimoError(f"MiMo HTTP {code}; no response body or credential was logged.") from None
        except (OSError, urllib.error.URLError):
            raise MimoError("MiMo connection failed or timed out.") from None


def api_get(path):
    if path != "/models":
        raise MimoError("Read-only escape hatch currently allows /models only.")
    with _open(path=path) as response:
        result = json.load(response)
    return {"models": [x.get("id") for x in result.get("data", [])]}


def _sse(response):
    event = []
    for raw in response:
        if len(raw) > 8_000_000:
            raise MimoError("Oversized SSE event.")
        line = raw.decode("utf-8").rstrip("\r\n")
        if not line:
            if event:
                joined = "\n".join(event)
                event = []
                if joined == "[DONE]":
                    return
                yield json.loads(joined)
        elif line.startswith("data:"):
            event.append(line[5:].lstrip())
    if event:
        joined = "\n".join(event)
        if joined != "[DONE]":
            yield json.loads(joined)


def _pcm(payload, on_chunk=None):
    started = time.perf_counter()
    first = None
    chunks = []
    total = 0
    finish = None
    usage = None
    with _open(payload) as response:
        if payload["stream"]:
            for event in _sse(response):
                if event.get("error"):
                    raise MimoError("MiMo returned a streaming error.")
                usage = event.get("usage") or usage
                for choice in event.get("choices", []):
                    finish = choice.get("finish_reason") or finish
                    audio = choice.get("delta", {}).get("audio") or {}
                    if audio.get("data"):
                        data = base64.b64decode(audio["data"], validate=True)
                        if first is None:
                            first = time.perf_counter() - started
                        total += len(data)
                        if total > 64_000_000:
                            raise MimoError("Audio exceeds the 64 MB per-segment bound.")
                        chunks.append(data)
                        if on_chunk:
                            on_chunk(data)
        else:
            body = json.load(response)
            choice = body["choices"][0]
            finish, usage = choice.get("finish_reason"), body.get("usage")
            data = base64.b64decode(choice["message"]["audio"]["data"], validate=True)
            with wave.open(io.BytesIO(data), "rb") as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                    raise MimoError("Unexpected WAV format; expected 24 kHz PCM16 mono.")
                data = wav.readframes(wav.getnframes())
            first = time.perf_counter() - started
            chunks.append(data)
            if on_chunk:
                on_chunk(data)
    if finish != "stop":
        raise MimoError("MiMo output incomplete or interrupted (finish_reason was not stop).")
    pcm = b"".join(chunks)
    if not pcm or len(pcm) % 2:
        raise MimoError("MiMo returned empty or malformed PCM.")
    return pcm, {"first_audio_seconds": round(first, 4), "total_seconds": round(time.perf_counter() - started, 4), "stream_events": len(chunks), "finish_reason": finish, "usage": usage}


def _write_wav(path, pcm):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)


def transcode(source, destination, speed=1.0, volume=1.0):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        installed = Path(r"D:\Applications\P47\FFmpeg\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe")
        if installed.is_file():
            ffmpeg = str(installed)
    if not ffmpeg:
        raise MimoError("ffmpeg is required for MP3 or speed/volume conversion.")
    if not 0.5 <= speed <= 2.5 or not 0 <= volume <= 3:
        raise MimoError("Speed or volume is outside the supported range.")
    filters = f"atempo={speed},volume={volume}"
    result = subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-af", filters, str(destination)], capture_output=True, timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise MimoError("ffmpeg could not convert the generated audio.")


def synthesize(text, out, *, mode="preset", voice=None, style="", reference=None, stream=None, cache=True, chunk_chars=400, on_chunk=None, speed=1.0, volume=1.0):
    if not 0.5 <= speed <= 2.5 or not 0 <= volume <= 3:
        raise MimoError("Speed or volume is outside the supported range.")
    out = Path(out).absolute()
    if out.exists():
        raise MimoError("Output already exists; use a new output path.")
    if out.suffix.lower() not in (".wav", ".mp3"):
        raise MimoError("Output must have a .wav or .mp3 extension.")
    stream = mode == "preset" if stream is None else stream
    voice = (voice or default_voice(text)) if mode == "preset" else None
    texts = split_text(text, chunk_chars)
    template = build_request(texts[0], mode, voice, style, reference, stream)
    out.parent.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    segments, pcm_parts = [], []
    key_config = {"model": MODELS[mode], "voice": voice, "style": style, "reference": reference_url(reference)[1] if reference else None, "stream": stream, "schema": 1}
    for i, part in enumerate(texts):
        request = {**template, "messages": [*template["messages"][:-1], {"role": "assistant", "content": part}]}
        digest = hashlib.sha256(json.dumps({**key_config, "text": part}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        cached = CACHE / (digest + ".wav")
        hit = cache and cached.exists()
        if hit:
            with wave.open(str(cached), "rb") as wav:
                if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (SAMPLE_RATE, 1, 2):
                    raise MimoError("Cached WAV has an invalid format.")
                pcm = wav.readframes(wav.getnframes())
            metrics = {"first_audio_seconds": 0, "total_seconds": 0, "stream_events": 0, "finish_reason": "cache"}
            if on_chunk:
                for offset in range(0, len(pcm), 16384):
                    on_chunk(pcm[offset:offset + 16384])
        else:
            pcm, metrics = _pcm(request, on_chunk)
            if cache:
                with tempfile.NamedTemporaryFile(dir=CACHE, suffix=".wav", delete=False) as handle:
                    temporary = Path(handle.name)
                try:
                    _write_wav(temporary, pcm)
                    temporary.replace(cached)
                finally:
                    temporary.unlink(missing_ok=True)
        pcm_parts.append(pcm)
        segments.append({"index": i, "characters": len(part), "text_sha256": hashlib.sha256(part.encode("utf-8")).hexdigest(), "cache_hit": hit, "audio_seconds": len(pcm) / (SAMPLE_RATE * 2), **metrics})
    pcm = b"".join(pcm_parts)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix="mimo-") as temp:
        wav_path = Path(temp) / "audio.wav"
        _write_wav(wav_path, pcm)
        prepared = wav_path
        if out.suffix.lower() == ".mp3" or speed != 1 or volume != 1:
            prepared = Path(temp) / ("converted" + out.suffix)
            transcode(wav_path, prepared, speed, volume)
        # Exclusive creation refuses races or replacement of existing user files.
        with out.open("xb") as target, prepared.open("rb") as source:
            shutil.copyfileobj(source, target)
    result = {"schema_version": 1, "provider": "xiaomi-mimo", "model": MODELS[mode], "voice": voice, "path": str(out), "bytes": out.stat().st_size, "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "characters": len(text), "sample_rate": SAMPLE_RATE, "audio_seconds": round(len(pcm) / (SAMPLE_RATE * 2) / speed, 4), "first_audio_seconds": segments[0]["first_audio_seconds"], "total_seconds": round(time.perf_counter() - started, 4), "segments": segments, "word_timestamps": False, "stream_requested": stream, "text_rewritten": False, "speed": speed}
    out.with_suffix(out.suffix + ".json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
