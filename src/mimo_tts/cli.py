from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
import wave
from pathlib import Path

from .client import ARTIFACTS, BASE_URL, MODELS, MimoError, api_get, build_request, credential, split_text, synthesize, voices
from .router import synthesize, voices, selected_provider, openai_key


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise MimoError(message)


def parser():
    p = Parser(description="Shared TTS: OpenAI by local configuration, with retained MiMo modes.")
    p.add_argument("--json", action="store_true", help="Stable JSON envelope; errors never include API bodies or keys")
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor", help="Check local configuration; optionally synthesize a small probe")
    d.add_argument("--probe", action="store_true")
    sub.add_parser("voices", help="List the eight official preset voice IDs")
    sub.add_parser("models", help="List the supported model families and streaming capabilities")
    s = sub.add_parser("synthesize", help="Synthesize text to WAV/MP3, preserving input text")
    source = s.add_mutually_exclusive_group(required=True)
    source.add_argument("--text")
    source.add_argument("--text-file", type=Path, help="UTF-8 file; - means stdin")
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--mode", choices=list(MODELS), default="preset")
    s.add_argument("--provider", choices=['openai','mimo'], help='Override the configured provider; MiMo remains available.')
    s.add_argument("--voice", help="Preset ID; default 茉莉 for Chinese or Mia for English")
    s.add_argument("--style", default="")
    s.add_argument("--reference", type=Path, help="Authorized WAV/MP3 sample for clone mode")
    s.add_argument("--no-cache", action="store_true")
    s.add_argument("--no-stream", action="store_true")
    s.add_argument("--chunk-chars", type=int, default=400)
    s.add_argument("--speed", type=float, default=1.0)
    s.add_argument("--volume", type=float, default=1.0, help="Postprocessing gain, from 0 to 3")
    s.add_argument("--dry-run", action="store_true", help="Validate without contacting MiMo or writing audio")
    c = sub.add_parser("compare", help="Generate preset/design/clone comparisons using a generated reference")
    c.add_argument("--text", default="今天我们测试文字转语音。请保持清晰自然的发音，注意句子之间的停顿。The quick brown fox jumps over the lazy dog.")
    c.add_argument("--out-dir", type=Path, default=ARTIFACTS / "comparisons")
    r = sub.add_parser("request", help="Read-only API escape hatch (GET /models)")
    r.add_argument("method", choices=["get"])
    r.add_argument("path", choices=["/models"])
    return p


def compare(text, directory):
    directory.mkdir(parents=True, exist_ok=True)
    style = "青年女性，声音温和清晰，普通话标准，英文发音自然。以平稳的正常语速朗读学习材料，不增加语气词或额外内容。"
    results = []
    for name, kwargs in [("preset", {}), ("design", {"mode": "design", "style": style}), ("clone", {"mode": "clone", "reference": directory / "design.wav"})]:
        print(f"Generating {name}...", file=sys.stderr, flush=True)
        try:
            results.append({"name": name, "ok": True, **synthesize(text, directory / (name + ".wav"), cache=False, **kwargs)})
        except (MimoError, OSError, ValueError, wave.Error) as exc:
            results.append({"name": name, "ok": False, "error": str(exc) if isinstance(exc, MimoError) else type(exc).__name__})
    (directory / "comparison.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"directory": str(directory), "results": results, "ok": all(x["ok"] for x in results)}


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.command == "doctor":
            if selected_provider()=='openai':
                openai_key()
                data={'provider':'openai','model':'gpt-realtime-2.1-mini','credential_present':True,'network_verified':False}
                if args.probe:
                    data['probe']=synthesize('Hello. This is an audio connection test.',ARTIFACTS/'probes'/(uuid.uuid4().hex+'.wav'),cache=False)
                    data['network_verified']=True
                print(json.dumps({'ok':True,'command':args.command,'data':data}));return 0
            try:
                _, source = credential()
                present = True
            except MimoError:
                source, present = "missing", False
            data = {"credential_present": present, "credential_source": source, "base_url": BASE_URL, "ffmpeg": bool(shutil.which("ffmpeg")), "network_verified": False}
            if args.probe:
                data["probe"] = synthesize("你好，这是 MiMo 语音连接测试。", ARTIFACTS / "probes" / (uuid.uuid4().hex + ".wav"), cache=False)
                data["network_verified"] = True
            ok = present
        elif args.command == "voices":
            data, ok = {"voices": voices()}, True
        elif args.command == "models":
            if selected_provider() == 'openai':
                data = {"provider": "openai", "models": [{"mode": key, "id": "gpt-realtime-2.1-mini", "low_latency_streaming": True} for key in ('preset', 'design')]}
            else:
                data = {"provider": "mimo", "models": [{"mode": key, "id": model, "low_latency_streaming": key == "preset"} for key, model in MODELS.items()]}
            ok = True
        elif args.command == "request":
            data, ok = api_get(args.path), True
        elif args.command == "compare":
            data = compare(args.text, args.out_dir / uuid.uuid4().hex[:10])
            ok = data["ok"]
        else:
            if not .5 <= args.speed <= 2.5 or not 0 <= args.volume <= 3:
                raise MimoError("Speed or volume is outside the supported range.")
            if args.out.suffix.lower() not in (".wav", ".mp3"):
                raise MimoError("Output must have a .wav or .mp3 extension.")
            text = args.text if args.text is not None else (sys.stdin.read() if str(args.text_file) == "-" else args.text_file.read_text(encoding="utf-8-sig"))
            options = dict(mode=args.mode, voice=args.voice, style=args.style, reference=args.reference, stream=False if args.no_stream else None, chunk_chars=args.chunk_chars)
            if args.dry_run:
                parts = split_text(text, args.chunk_chars)
                provider = args.provider or selected_provider()
                if provider == 'openai':
                    if args.mode == 'clone' or args.reference is not None:
                        raise MimoError('OpenAI cloning is not configured. Select the retained MiMo provider explicitly for cloning.')
                    model = 'gpt-realtime-2.1-mini'
                else:
                    for part in parts:
                        build_request(part, args.mode, args.voice, args.style, args.reference, not args.no_stream and args.mode == "preset")
                    model = MODELS[args.mode]
                data = {"dry_run": True, "provider": provider, "characters": len(text), "segments": len(parts), "model": model, "out": str(args.out)}
            else:
                data = synthesize(text, args.out, provider=args.provider, cache=not args.no_cache, speed=args.speed, volume=args.volume, **options)
            ok = True
        print(json.dumps({"ok": ok, "command": args.command, "data": data}, ensure_ascii=False))
        return 0 if ok else 1
    except (MimoError, OSError, ValueError, KeyError, IndexError, wave.Error) as exc:
        message = str(exc) if isinstance(exc, MimoError) else type(exc).__name__ + ": input, output or response could not be processed."
        print(json.dumps({"ok": False, "error": {"type": type(exc).__name__, "message": message}}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
