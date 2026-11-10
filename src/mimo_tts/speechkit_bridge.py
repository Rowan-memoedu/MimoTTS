"""Keep SpeechKit's audio/manifest/cue contract with explicit provider routing."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .adapters import selected_voice
from .client import MimoError
from .router import synthesize


def synthesize_compatible(*, text, output, profile, voice, speech_rate, instruct, force_refresh, ffprobe, provider=None):
    if profile.get("voice_cloning", False):
        raise MimoError("SpeechKit preset synthesis does not enable voice cloning; use mimo-tts clone explicitly.")
    target = Path(output).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    selected = selected_voice(text, voice or profile.get("voice", ""))
    if provider=='mimo':
        from .client import VOICES
        supplied=(voice or profile.get('voice','')).removeprefix('mimo-')
        selected=supplied if supplied in VOICES else 'Mia'
    rate = speech_rate if speech_rate is not None else profile.get("speech_rate", 0)
    style = instruct if instruct is not None else profile.get("instruct", [])
    if isinstance(style, list):
        style = "\n".join(style)
    # Generate and validate a sibling temporary file before replacing the requested
    # output, matching SpeechKit's pre-existing overwrite contract.
    with tempfile.TemporaryDirectory(dir=target.parent, prefix="speechkit-mimo-") as temp:
        prepared = Path(temp) / ("audio" + target.suffix)
        result = synthesize(text, prepared, provider=provider, voice=selected, speed=1 + rate / 100,
                            style=style or "", cache=not force_refresh)
        probe = subprocess.run([ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(prepared)],
                               capture_output=True, text=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        probe.check_returncode()
        info = json.loads(probe.stdout)
        stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
        metadata = dict(codec=stream["codec_name"], sample_rate=int(stream["sample_rate"]),
                        channels=stream["channels"], duration_seconds=float(info["format"]["duration"]), bytes=prepared.stat().st_size)
        os.replace(prepared, target)
    cache_hit = all(s["cache_hit"] for s in result["segments"])
    result["path"] = str(target)
    cache_key = hashlib.sha256(json.dumps(dict(provider=result["provider"], model=result["model"],
        voice=selected, text_sha256=result["text_sha256"], speed=result["speed"], style=style),
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    manifest = dict(schema_version=1, created_at=datetime.now(timezone.utc).isoformat(), provider=result['provider'],
                    provider_package=dict(name="fy-mimo-tts", version="0.1.0"), request_id=None,
                    request_attempts=sum(not s["cache_hit"] for s in result["segments"]), request_ids=[],
                    input=dict(sha256=result["text_sha256"], characters=len(text)),
                    profile=dict(path=profile["_profile_path"], sha256=profile["_profile_sha256"],
                                 voice=selected, resource_id=result["model"], speech_rate=rate),
                    cache=dict(hit=cache_hit, key=cache_key),
                    audio=dict(path=str(target), sha256=digest, **metadata), words_path=None,
                    word_timestamps=False, usage=None, mimo=result)
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    # Old timestamp sidecars cannot describe the replacement audio.
    target.with_suffix(target.suffix + ".words.json").unlink(missing_ok=True)
    return dict(audio_path=str(target), manifest_path=str(manifest_path), words_path=None,
                cache_hit=cache_hit, duration_seconds=metadata["duration_seconds"], sha256=digest,
                request_id=None, provider=result['provider'], word_timestamps=False)
