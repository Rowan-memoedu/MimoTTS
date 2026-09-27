"""Produce same-text old/new recordings and an offline, playable comparison page."""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from mimo_tts.client import synthesize

ROOT = Path(r"D:\Artifacts\MimoTTS")
PROJECT = Path(__file__).resolve().parents[1]
PYTHON = Path(r"D:\AppData\MimoTTS\venv\Scripts\python.exe")
EDGE = Path(r"D:\AppData\WebLilt\venv\Scripts\python.exe")
CLIPPER_SETTINGS = Path(r"D:\AppData\KnowledgeClipper\language-settings.json")


def command(args, text=None, timeout=300):
    result = subprocess.run([str(x) for x in args], input=text, encoding="utf-8", text=True, capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        # Provider output is not copied to the report; it may include source material.
        raise RuntimeError("Command failed with exit code " + str(result.returncode))
    return result.stdout


def probe(path):
    data = json.loads(command([shutil.which("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", path]))
    duration = float(data["format"]["duration"])
    if duration <= .1 or path.stat().st_size < 100:
        raise RuntimeError("Audio is empty or too short")
    command([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-i", path, "-f", "null", "-"])
    return {"audio_seconds": duration, "audio_format": data["streams"][0], "bytes": path.stat().st_size}


def old_audio(case, output):
    kind = case["old_provider"]
    text = case["text"]
    if kind == "edge":
        request = {"text": text, "voice": case["old_voice"], "out": str(output), "rate": case.get("rate", 0), "volume": case.get("volume", 0), "pitch": case.get("pitch", 0)}
        python = Path(case.get("python", str(EDGE)))
        return json.loads(command([python, "-X", "utf8", PROJECT / "scripts" / "edge_baseline.py"], json.dumps(request, ensure_ascii=False)))
    if kind == "doubao":
        text_path = output.with_suffix(".txt")
        text_path.write_text(text, encoding="utf-8")
        command([shutil.which("speech-kit"), "--json", "tts", "synthesize", "--text-file", text_path, "--out", output, "--provider", "doubao"])
        return {"provider": "Doubao seed-tts-2.0", "voice": "zh_female_vv_uranus_bigtts", "first_audio_seconds": None}
    script = "$r=[Console]::In.ReadToEnd()|ConvertFrom-Json; Add-Type -AssemblyName System.Speech; $s=[System.Speech.Synthesis.SpeechSynthesizer]::new(); $v=$s.Voice; $s.SetOutputToWaveFile($r.out); $s.Speak($r.text); $s.Dispose(); @{voice=$v.Name;culture=$v.Culture.Name;provider='Windows System.Speech'}|ConvertTo-Json -Compress"
    # Windows PowerShell is the existing application's actual System.Speech host.
    import base64
    encoded = base64.b64encode(("[Console]::InputEncoding=[Text.UTF8Encoding]::new();[Console]::OutputEncoding=[Text.UTF8Encoding]::new();" + script).encode("utf-16-le")).decode()
    return json.loads(command(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], json.dumps({"text": text, "out": str(output)}, ensure_ascii=False)))


def run_case(case, directory):
    case = dict(case)
    records = []
    for side in ("old", "new"):
        extension = ".wav" if side == "new" or case["old_provider"] == "windows" else ".mp3"
        output = directory / "audio" / (case["id"] + "-" + side + extension)
        started = time.perf_counter()
        print(case["id"] + " " + side, flush=True)
        try:
            if side == "old":
                data = old_audio(case, output)
            else:
                data = synthesize(case["text"], output, voice=case["new_voice"], cache=False, speed=1 + case.get("rate", 0)/100, volume=1 + case.get("volume", 0)/100)
            wall = time.perf_counter() - started
            records.append({"side": side, "ok": True, "path": "audio/" + output.name, "wall_seconds": wall, **data, **probe(output)})
            # Keep relative paths in the portable report.
            records[-1]["path"] = "audio/" + output.name
        except Exception as exc:
            records.append({"side": side, "ok": False, "error": type(exc).__name__, "wall_seconds": time.perf_counter()-started})
    case["results"] = records
    return case


def audio_card(record, title):
    title = html.escape(title)
    if not record.get("ok", True):
        return f'<div class="audio-card failed"><h3>{title}</h3><p>本轮失败：{html.escape(record["error"])}。不将其视为通过。</p></div>'
    first = record.get("first_audio_seconds")
    first_text = f'{first:.2f} 秒' if first is not None else "未单独测量"
    wall = record.get("wall_seconds", record.get("total_seconds", 0))
    voice = record.get("voice") or record.get("model", "")
    return f'''<div class="audio-card"><div class="audio-heading"><h3>{title}</h3><span>{html.escape(str(voice))}</span></div>
<audio controls preload="metadata" src="{html.escape(record['path'])}"></audio>
<div class="metrics"><span><b>{wall:.2f}s</b> 完整生成</span><span><b>{first_text}</b> 首段数据</span><span><b>{record['audio_seconds']:.1f}s</b> 录音时长</span></div>
<a class="download" download href="{html.escape(record['path'])}">下载录音</a></div>'''


def render(directory, cases, models, created_at=None):
    sections = []
    for case in cases:
        cards = audio_card(case["results"][0], "旧方案 · " + case["old_label"]) + audio_card(case["results"][1], "MiMo · 预置音色")
        sections.append(f'''<section class="case" id="{case['id']}"><div class="case-title"><span class="number">{len(sections)+1:02}</span><div><h2>{html.escape(case['title'])}</h2><p>{html.escape(case['note'])}</p></div><button class="pair-play" type="button">顺序播放旧 → 新</button></div><blockquote>{html.escape(case['text'])}</blockquote><div class="pair">{cards}</div></section>''')
    model_cards = "".join(audio_card(x, {"preset": "预置音色", "design": "VoiceDesign", "clone": "VoiceClone"}[x["name"]]) for x in models)
    total = sum(len(x["results"]) for x in cases) + len(models)
    passed = sum(x.get("ok", True) for c in cases for x in c["results"]) + sum(x.get("ok", True) for x in models)
    created_at = created_at or datetime.now().astimezone().isoformat()
    status_path = Path(r"D:\Artifacts\MimoTTS\production\20260927\status.json")
    production = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
    payload = {"created_at": created_at, "cases": cases, "models": models, "audio_files": total, "successful_audio_files": passed, "subjective_listening": "pending", "production_switched": bool(production) and all(a["activation"] == "active" for a in production.get("applications", [])), "production": production}
    (directory / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    template = (PROJECT / "templates" / "comparison.html").read_text(encoding="utf-8")
    content = template.replace("{{CASES}}", "\n".join(sections)).replace("{{MODELS}}", model_cards).replace("{{COUNT}}", f"{passed}/{total}").replace("{{SCENES}}", str(len(cases))).replace("{{TIME}}", datetime.fromisoformat(created_at).strftime("%Y-%m-%d %H:%M"))
    rows = "".join(f'<tr><td>{html.escape(a["name"])}</td><td>{html.escape(a["status"])}</td></tr>' for a in production.get("applications", []))
    section = f'<section class="case" id="production"><h2>正式切换进度</h2><p>已批准切换；基于当前源码合并，保留测试之后的更新。运行状态以本表为准。</p><table><thead><tr><th>入口</th><th>当前状态</th></tr></thead><tbody>{rows}</tbody></table><p><a href="../../production/20260927/deployment.md">迁移与验收记录</a> · <a href="../../production/20260927/status.json">正式状态 JSON</a></p></section>' if production else ""
    content = content.replace("{{PRODUCTION}}", section)
    if production:
        content = content.replace("运行状态以本表为准。", "运行状态以本表为准。当前中英文默认音色统一为 Mia，取自下方第二组零碎知识剪藏的新录音；历史对照录音保留原始音色。")
        content = content.replace("正式版本保持现状；本页为独立测试产物。", "新旧录音保持原始对照；正式迁移状态见下表。").replace("正式软件尚未切换。", "此表为历史隔离包，不能直接用于正式安装。").replace("隔离测试版本", "历史隔离测试版本")
    (directory / "index.html").write_text(content, encoding="utf-8")
    return payload


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", type=Path, help="Re-render existing results and verify audio without API calls")
    args = parser.parse_args()
    if args.refresh:
        saved = json.loads((args.refresh / "results.json").read_text(encoding="utf-8"))
        for record in [r for c in saved["cases"] for r in c["results"]] + saved["models"]:
            if record.get("ok"):
                probe(args.refresh / record["path"])
        render(args.refresh, saved["cases"], saved["models"], saved["created_at"])
        print(json.dumps({"refreshed": str(args.refresh / "index.html"), "new_api_calls": 0}))
        return
    directory = ROOT / "reports" / datetime.now().strftime("%Y%m%d-%H%M%S")
    (directory / "audio").mkdir(parents=True)
    settings = json.loads(CLIPPER_SETTINGS.read_text(encoding="utf-8-sig"))
    english = settings.get("englishVoice", "en-US-AnaNeural").replace("MultilingualNeural", "Neural")
    cases = [
        {"id": "weblilt", "title": "WebLilt · 英文网页", "text": "A good explanation connects a new idea to something you already understand. Read the whole sentence first, then return to the unfamiliar words.", "old_provider": "edge", "old_voice": "en-US-AriaNeural", "old_label": "Edge TTS / Aria", "new_voice": "Mia", "note": "旧版默认声线；两侧输入完全相同。MiMo 测试版保留句子高亮，缺少逐词时间戳。"},
        {"id": "clipper", "title": "零碎知识剪藏 · 当前英文朗读设置", "text": "The word kinetic describes motion. Kinetic energy depends on both the mass and the speed of an object.", "old_provider": "edge", "old_voice": english, "old_label": "Edge TTS / " + english, "new_voice": "Mia", "python": settings["pythonPath"], "rate": settings.get("ratePercent", 0), "volume": settings.get("volumePercent", 0), "pitch": settings.get("pitchHz", 0), "note": "按本机实际设置读取：英文声线去除 Multilingual 后缀，与当前程序行为一致；两侧保留当前语速和音量。MiMo 采用音频后处理调整。"},
        {"id": "anki", "title": "Anki / SuperFreeTTS · 英语卡片", "text": "Acceleration is the rate of change of velocity. A change in direction is also a change in velocity, even when the speed stays constant.", "old_provider": "edge", "old_voice": "en-US-AriaNeural", "old_label": "Edge TTS / Aria", "new_voice": "Mia", "note": "复用旧版默认英语声线作基线；MiMo 预生成 MP3，保留逐块播放。正式卡片和复习记录未修改。"},
        {"id": "openfocus", "title": "OpenFocus · 中文语音提醒", "text": "请把注意力回到当前任务。先完成眼前的一小步，再继续下一项。如果需要休息，请先保存当前进度。", "old_provider": "windows", "old_label": "Windows 系统语音", "new_voice": "茉莉", "note": "旧方案使用程序原有的 System.Speech 默认声线；新方案需要联网。此对比只生成录音，没有启用督学或限制规则。"},
        {"id": "speechkit", "title": "通用 TTS · 中文讲解与配音", "text": "理解一个概念，不只是记住它的定义。试着用自己的话解释它，举一个例子，再想一想它在什么情况下不适用。", "old_provider": "doubao", "old_label": "豆包 / speech-kit", "new_voice": "茉莉", "note": "旧方案使用现有 speech-kit 的豆包配置；MiMo 共用新封装。这里比较自然度、停顿与发音，暂不评价字幕时间轴适配。"},
    ]
    obsidian_path = Path(r"D:\Workspaces\新建文件夹\.obsidian\plugins\note-reader-cosyvoice-focus\data.json")
    if obsidian_path.exists():
        reader = json.loads(obsidian_path.read_text(encoding="utf-8"))
        voice = reader.get("mimoVoice", "Mia")
        cases.append({"id": "obsidian", "title": "Obsidian 阅读器 · 现用语速", "text": "A new idea becomes easier to understand when you connect it to what you already know. Pause at the end of a paragraph, then read the next part.",
            "old_provider": "edge", "old_voice": reader.get("edgeTtsVoice", "en-GB-RyanNeural"), "old_label": "Edge TTS / " + reader.get("edgeTtsVoice", "en-GB-RyanNeural"),
            "new_voice": "Mia" if voice == "auto" else voice, "rate": round((reader.get("speed", 1) - 1) * 100),
            "note": "旧声线与语速取自本机阅读器配置；新方案使用 MiMo。保留分段、数学朗读、高亮及右侧面板。"})
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda case: run_case(case, directory), cases))
    # Reuse the already verified same-text three-model run, with its original timings.
    candidates = sorted((ROOT / "comparisons").glob("*/comparison.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    models = json.loads(candidates[0].read_text(encoding="utf-8")) if candidates else []
    for model in models:
        if model.get("ok"):
            source = Path(model["path"])
            target = directory / "audio" / ("model-" + model["name"] + source.suffix)
            shutil.copyfile(source, target)
            model["path"] = "audio/" + target.name
            model.update(probe(target))
    payload = render(directory, results, models)
    (ROOT / "latest-report.json").write_text(json.dumps({"path": str(directory / "index.html"), "results": str(directory / "results.json")}), encoding="utf-8")
    print(json.dumps({"report": str(directory / "index.html"), "passed": payload["successful_audio_files"], "total": payload["audio_files"]}))


if __name__ == "__main__":
    main()
