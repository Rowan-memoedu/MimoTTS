---
name: mimo-tts
description: Generate speech with the local MiMo TTS CLI, using preset voices, voice design, or an authorized voice sample; create playable comparisons when testing speech providers.
---

# MiMo speech

The shared implementation is `D:\Projects\MimoTTS`. Run `D:\AppData\MimoTTS\bin\mimo-tts.cmd`; new terminals also expose `mimo-tts` on PATH. It reads `MIMO_API_KEY` from the current process or Windows user environment, so a stale parent process does not require re-entering the key. Do not display the key or place it in arguments/files.

Use `--json doctor` to check setup and `--json doctor --probe` when a live connection check is needed. Credentials present alone do not prove the API works.

Default to `preset` and Mia for both Chinese and English, as selected from the Clipper comparison recording. Explicit voice selection remains available. Use `design --style` for a described voice, and `clone --reference` for a user-authorized WAV/MP3 or a generated voice. Design/clone do not provide the same low-latency streaming behavior as preset. Free pricing was verified on 2026-09-27; recheck the official model page before making later cost claims.

```powershell
& 'D:\AppData\MimoTTS\bin\mimo-tts.cmd' --json synthesize --text '你好，这是语音测试。' --out 'D:\Artifacts\MimoTTS\hello.wav'
& 'D:\AppData\MimoTTS\bin\mimo-tts.cmd' --json synthesize --text-file 'D:\Artifacts\narration.txt' --mode design --style '青年女性，普通话清晰，语气温和' --out 'D:\Artifacts\MimoTTS\narration.wav'
```

Prefer UTF-8 `--text-file` (or `--text-file -` for stdin) for long text. Outputs refuse overwrite: choose a new path. WAV is dependency-free; MP3 and rate/volume adjustment use installed ffmpeg. Preserve input content, including parentheses; the client chunks without rewriting and disables design text optimization. Actual pronunciation and omissions still need listening checks.

Return the playable local audio, not just a success log. `compare` generates preset/design/clone recordings with a generated reference; `scripts/create_comparison_report.py` builds the application-scene old/new HTML report. The latest page path is in `D:\Artifacts\MimoTTS\latest-report.json`.

Application adapters live in `src\mimo_tts\adapters.py`. Test packages use `D:\Artifacts\MimoTTS\test-builds` and separate data. Production migration was authorized on 2026-09-27. Merge provider changes into each app's current source and rebuild; never promote the old test snapshots over later updates. Record activation/restart status in `D:\Artifacts\MimoTTS\production\20260927`; do not claim a running app has switched until its runtime is verified. MiMo supplies no verified word timestamps, so WebLilt uses sentence highlighting. See the project README for each test launcher and current validation.
