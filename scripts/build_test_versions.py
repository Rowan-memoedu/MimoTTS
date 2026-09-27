"""Reproducible test packaging. Reads app sources; never edits installed applications."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
PROJECTS = Path(r"D:\Projects")
PYTHON = Path(r"D:\AppData\MimoTTS\venv\Scripts\python.exe")
ROOT = Path(r"D:\Artifacts\MimoTTS\test-builds")
BUILD_CACHE = Path(r"D:\Caches\MimoTTS\clipper-build-source")
APP_DATA = Path(r"D:\AppData\MimoTTS\test-apps")


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def replace(path, old, new, minimum=1):
    text = path.read_text(encoding="utf-8-sig")
    count = text.count(old)
    if count < minimum:
        raise RuntimeError(f"Source changed: expected pattern missing in {path.name}")
    write(path, text.replace(old, new))


def snapshot(source, target, folders=None):
    target.mkdir(parents=True, exist_ok=True)
    tracked = subprocess.check_output(["git", "-C", str(source), "ls-files", "-z"]).decode("utf-8").split("\0")
    copied = {}
    for relative in tracked:
        if not relative:
            continue
        path = source / relative
        if not path.is_file() or path.is_symlink():
            continue
        if folders and Path(relative).parts[0] not in folders:
            continue
        if any(p in ("__pycache__", "node_modules", "bin", "obj", ".git") for p in Path(relative).parts):
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        copied[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return {"source": str(source), "commit": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"]).decode().strip(), "files": copied}


def bootstrap(module, function="main"):
    return f"import sys\nsys.path.insert(0, {str(PROJECT / 'src')!r})\nfrom {module} import {function}\nraise SystemExit({function}())\n"


def build_weblilt():
    target = ROOT / "WebLilt"
    receipt = snapshot(PROJECTS / "WebLilt", target, {"extension", "native"})
    manifest_path = target / "extension" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    key_path = ROOT / "weblilt-test-public-key.txt"
    if key_path.exists():
        public_key = key_path.read_text().strip()
    else:
        public_key = subprocess.check_output(["pwsh", "-NoProfile", "-Command", "$rsa=[Security.Cryptography.RSA]::Create(2048); [Convert]::ToBase64String($rsa.ExportSubjectPublicKeyInfo()); $rsa.Dispose()"], text=True).strip()
        write(key_path, public_key)
    extension_id = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(base64.b64decode(public_key)).hexdigest()[:32])
    manifest.update(name="WebLilt · MiMo 对比测试", key=public_key, description="MiMo 测试：原页点读、句子高亮、独立停顿；没有词级时间戳。")
    for command in manifest.get("commands", {}).values():
        command.pop("suggested_key", None)
    write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    for path in (target / "extension").glob("*.js"):
        text = path.read_text(encoding="utf-8")
        for old, new in {"com.weblilt.tts": "com.weblilt.mimo_test", "en-US-AriaNeural": "mimo-Mia", "en-US-GuyNeural": "mimo-Dean", "en-GB-SoniaNeural": "mimo-Chloe", "en-GB-RyanNeural": "mimo-Milo", "微软完整英文音色": "MiMo 英文音色", "微软音色": "MiMo 音色", "微软服务": "MiMo 服务", 'id="pitch" type=': 'id="pitch" disabled type=', "音高 Hz": "音高（测试停用）"}.items():
            text = text.replace(old, new)
        write(path, text)
    setup = target / "extension" / "setup.html"
    replace(setup, "微软", "MiMo")
    write(setup, setup.read_text(encoding="utf-8").replace("</body>", "<p>此版本使用 MiMo：保留句子高亮，不提供逐词时间戳；音高固定为 0。原版扩展保持独立。</p></body>"))
    host_path = target / "native" / "host.py"
    host = host_path.read_text(encoding="utf-8")
    host = host.replace("import edge_tts", "from mimo_tts.adapters import weblilt_synthesize\nfrom mimo_tts.client import voices as mimo_voices")
    host = host.replace('EXTENSION_ID = "lcjhjjplhiikgobpfkkgbobgacnljeje"', f'EXTENSION_ID = "{extension_id}"')
    host, count = re.subn(r"async def synthesize\(request, send\):.*?(?=\n\nasync def run)", "async def synthesize(request, send):\n    await weblilt_synthesize(request, send)\n", host, flags=re.S)
    if count != 1:
        raise RuntimeError("WebLilt synthesis protocol changed")
    host = host.replace('"engine": "edge-tts", "engineVersion": version("edge-tts")', '"engine": "MiMo test", "engineVersion": "0.1.0"')
    host = host.replace('[{"name": v["ShortName"], "locale": v["Locale"], "gender": v["Gender"], "label": v["FriendlyName"]} for v in await edge_tts.list_voices()]', '[{"name": "mimo-" + v["id"], "locale": "en-US" if v["language"] == "en" else "zh-CN", "gender": v["gender"], "label": v["id"]} for v in mimo_voices()]')
    write(host_path, host)
    launcher = target / "mimo-host.cmd"
    write(launcher, f'@echo off\n"{PYTHON}" -X utf8 -u "{host_path}" %*\n')
    native_manifest = target / "com.weblilt.mimo_test.json"
    write(native_manifest, json.dumps({"name": "com.weblilt.mimo_test", "description": "Isolated MiMo comparison host", "path": str(launcher), "type": "stdio", "allowed_origins": [f"chrome-extension://{extension_id}/"]}, indent=2))
    write(target / "Install-Native.ps1", "$ErrorActionPreference='Stop'\n$p='HKCU:\\Software\\Google\\Chrome\\NativeMessagingHosts\\com.weblilt.mimo_test'\nNew-Item -Path $p -Force | Out-Null\nSet-Item -Path $p -Value '" + str(native_manifest) + "'\n(Get-Item $p).GetValue('')\n")
    receipt["extension_id"] = extension_id
    return receipt


def build_anki():
    target = ROOT / "Anki" / "addon"
    receipt = snapshot(PROJECTS / "SuperFreeTTSReview", target, {"review_extension"})
    initializer = target / "review_extension" / "__init__.py"
    source = initializer.read_text(encoding="utf-8")
    source = source.replace("from ..superfreetts_addon import voice, context, constants", "from mimo_tts.adapters import AnkiBackend")
    source, count = re.subn(r"class Backend:.*?(?=class ReviewExtension:)", "Backend = AnkiBackend\n\n\n", source, flags=re.S)
    if count != 1:
        raise RuntimeError("Anki Backend protocol changed")
    source = source.replace("Backend(mw.hyper_tts)", "Backend()")
    source = source.replace("superfreetts_review", "mimo_test_review").replace("superfreetts_data", "mimo_test_data").replace("SuperFreeTTS 复习", "MiMo 对比测试")
    write(initializer, source)
    base = APP_DATA / "Anki"
    entry = f'''from pathlib import Path
import json
import os
import sys
from aqt import gui_hooks, mw
sys.path.insert(0, {str(PROJECT / "src")!r})
def opened():
    folder = Path(mw.pm.profileFolder()).resolve()
    base = Path({str(base)!r}).resolve()
    if base not in folder.parents:
        return  # This test addon never writes in a production profile.
    if not mw.col.models.by_name("MiMo TTS Test"):
        model = mw.col.models.new("MiMo TTS Test")
        for name in ("Front", "Back"):
            mw.col.models.add_field(model, mw.col.models.new_field(name))
        template = mw.col.models.new_template("MiMo")
        template["qfmt"] = "{{{{Front}}}}"
        template["afmt"] = "{{{{FrontSide}}}}<hr id=answer>{{{{Back}}}}"
        mw.col.models.add_template(model, template)
        mw.col.models.add(model)
        note = mw.col.new_note(model)
        note["Front"] = "The quick brown fox jumps over the lazy dog."
        note["Back"] = "这是一张独立的语音测试卡。<hr>A good explanation connects a new idea to something you already understand."
        mw.col.add_note(note, mw.col.decks.id("MiMo TTS Test"))
    if not hasattr(mw, "mimo_test_review"):
        from .review_extension import install
        install()
        mw.mimo_test_review.open()
    if os.environ.get("MIMO_TEST_CANARY_RESULT"):
        from aqt.qt import QTimer
        def canary():
            controller = mw.mimo_test_review
            try:
                notes = mw.col.find_notes('deck:"MiMo TTS Test"')
                if not notes or controller.queue or controller.busy:
                    QTimer.singleShot(1000, canary)
                    return
                media = list(Path(mw.col.media.dir()).glob("*.mp3"))
                report = dict(ok=bool(media) and not controller.failures, notes=len(notes), media_files=len(media), profile=str(folder), mode=controller.config["mode"], scope=controller.config["deck_roots"], failures=controller.failures, physical_playback_verified=False)
            except Exception as exc:
                report = dict(ok=False, error=type(exc).__name__)
            Path(os.environ["MIMO_TEST_CANARY_RESULT"]).write_text(json.dumps(report), encoding="utf-8")
            mw.unloadProfileAndExit()
        QTimer.singleShot(10000, canary)
gui_hooks.profile_did_open.append(opened)
'''
    write(target / "__init__.py", entry)
    write(target / "config.json", json.dumps({"review_extension": {"deck_roots": ["MiMo TTS Test"], "enabled": True, "mode": "english", "prefetch": True}}, indent=2))
    write(target / "manifest.json", json.dumps({"name": "MiMo TTS isolated comparison", "package": "mimo_tts_comparison", "min_point_version": 50}))
    addon_target = base / "addons21" / "mimo_tts_comparison"
    shutil.copytree(target, addon_target, dirs_exist_ok=True)
    package = ROOT / "Anki" / "MiMo-TTS-Test.ankiaddon"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in target.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(target))
    receipt["isolated_base"] = str(base)
    executable = Path.home() / "AppData/Local/Programs/Anki/Anki.exe"
    write(ROOT / "Anki" / "Start-Test.ps1", f"$ErrorActionPreference='Stop'\n$env:ANKI_BASE='{base}'\n$env:ANKI_SINGLE_INSTANCE_KEY='mimo-tts-isolated-test'\n& '{executable}' -b '{base}' -l en\n")
    return receipt


def build_openfocus():
    target = ROOT / "OpenFocus"
    receipt = snapshot(PROJECTS / "OpenFocus", target, {"openfocus"})
    media = target / "openfocus" / "supervision" / "media.py"
    write(media, media.read_text(encoding="utf-8") + "\n# Isolated build provider injection; no production registration.\nfrom mimo_tts.adapters import OpenFocusVoice as Voice\n")
    write(target / "Start-Test.ps1", f"$ErrorActionPreference='Stop'\nSet-Location -LiteralPath '{target}'\n& '{PYTHON}' -X utf8 -m openfocus --desktop --data-dir '{APP_DATA / 'OpenFocus'}'\n")
    write(target / "voice-preview.py", f"import tkinter as tk\nfrom tkinter import ttk\nfrom mimo_tts.adapters import OpenFocusVoice\nr=tk.Tk(); r.title('OpenFocus · MiMo 提醒测试'); r.geometry('540x240'); v=OpenFocusVoice()\nt=tk.Text(r,height=7); t.pack(fill='both',expand=True,padx=16,pady=12); t.insert('1.0','请把注意力回到当前任务。先完成眼前的一小步，再继续下一项。')\nttk.Button(r,text='播放 MiMo 提醒',command=lambda:v.speak(t.get('1.0','end').strip())).pack()\nr.protocol('WM_DELETE_WINDOW',lambda:(v.close(),r.destroy())); r.mainloop()\n")
    write(target / "Preview-Voice.ps1", f"& '{PYTHON}' -X utf8 '{target / 'voice-preview.py'}'\n")
    return receipt


def prepare_clipper():
    source = PROJECTS / "RemNote Quick Clipper"
    receipt = snapshot(source, BUILD_CACHE)
    # Include explicit build inputs even when they are ignored verification files.
    for project in source.rglob("*.csproj"):
        if any(p in ("obj", "bin", "node_modules") for p in project.parts):
            continue
        for item in ET.parse(project).iter("Content"):
            include = item.get("Include", "")
            if not include or any(c in include for c in "*?;$"):
                continue
            original = (project.parent / include.replace("\\", "/")).resolve()
            if original.is_file() and source in original.parents:
                relative = original.relative_to(source)
                destination = BUILD_CACHE / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                receipt["files"][str(relative)] = hashlib.sha256(original.read_bytes()).hexdigest()
    for path in BUILD_CACHE.rglob("*.cs"):
        text = path.read_text(encoding="utf-8-sig")
        changed = text.replace(r"D:\Caches\KnowledgeClipper", r"D:\Caches\MimoTTS\KnowledgeClipper").replace(r"D:\AppData\KnowledgeClipper", str(APP_DATA / "KnowledgeClipper"))
        if changed != text:
            write(path, changed)
    instance = BUILD_CACHE / "src" / "SingleInstanceCoordinator.cs"
    replace(instance, "KnowledgeClipper.SingleInstance", "KnowledgeClipper.MimoTest.SingleInstance")
    replace(instance, "RemNoteQuickClipper.SingleInstance", "RemNoteQuickClipper.MimoTest.SingleInstance")
    diagnostics = BUILD_CACHE / "src" / "StartupDiagnostics.cs"
    replace(diagnostics, "KnowledgeClipper.SingleInstance", "KnowledgeClipper.MimoTest.SingleInstance")
    replace(diagnostics, "RemNoteQuickClipper.SingleInstance", "RemNoteQuickClipper.MimoTest.SingleInstance")
    replace(instance, "if (process.Id != current) return process;", "if (process.Id != current && string.Equals(SafeProcessPath(process), Process.GetCurrentProcess().MainModule.FileName, StringComparison.OrdinalIgnoreCase)) return process;")
    replace(instance, 'Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "KnowledgeClipper", "logs")', '@"' + str(APP_DATA / "KnowledgeClipper" / "logs") + '"')
    models = BUILD_CACHE / "workflow" / "Models.cs"
    for old, new in [(r"D:\Applications\RemNoteQuickClipperRuntime\edge-tts-7.2.8\Scripts\python.exe", str(PYTHON)), ('= "zh-CN-XiaoxiaoNeural";', '= "茉莉";'), ('= "en-US-AnaNeural";', '= "Mia";'), ('= "http://127.0.0.1:8765";', '= "http://127.0.0.1:48991";'), ('= "Alt+Shift+《";', '= "";'), ('= "Alt+Shift+/";', '= "";')]:
        replace(models, old, new)
    # All external writes from a test instance target closed loopback endpoints.
    connection = BUILD_CACHE / "workflow" / "RemNoteConnection.cs"
    if connection.exists():
        replace(connection, "43111", "48992")
    voice_catalog = BUILD_CACHE / "workflow" / "SpeechVoiceCatalog.cs"
    text = voice_catalog.read_text(encoding="utf-8")
    replacement = 'info.ArgumentList.Add("import json; from mimo_tts.client import voices; print(json.dumps([{\'ShortName\':v[\'id\'],\'Locale\':\'en-US\' if v[\'language\']==\'en\' else \'zh-CN\',\'Gender\':v[\'gender\']} for v in voices()]))");'
    text, count = re.subn(r'info.ArgumentList.Add\("import asyncio,json,edge_tts,sys.*?"\);', lambda _: replacement, text)
    if count != 1:
        raise RuntimeError("Clipper voice discovery changed")
    write(voice_catalog, text)
    write(BUILD_CACHE / "helpers" / "stream_speech.py", bootstrap("mimo_tts.adapters"))
    dependencies = source / "helpers" / "node_modules"
    if dependencies.exists():
        shutil.copytree(dependencies, BUILD_CACHE / "helpers" / "node_modules", dirs_exist_ok=True)
    config_path = BUILD_CACHE / "appsettings.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    compat = ROOT / "KnowledgeClipper" / "mimo-speechkit.cmd"
    write(compat, f'@echo off\n"{PYTHON}" -X utf8 -m mimo_tts.speechkit_compat %*\n')
    config.update(WorkDirectory=str(APP_DATA / "KnowledgeClipper"), PythonPath=str(PYTHON), RemnoteMcpUrl="http://127.0.0.1:48992/mcp", SpeechKitPath=str(compat))
    write(config_path, json.dumps(config, ensure_ascii=False, indent=2))
    receipt["build_source"] = str(BUILD_CACHE)
    target = ROOT / "KnowledgeClipper"
    executable = target / "release" / "RemNoteQuickClipper.Desktop" / "Release" / "net8.0-windows" / "win-x64" / "KnowledgeClipper.exe"
    write(target / "Build.ps1", f"& pwsh -NoProfile -File '{BUILD_CACHE / 'build.ps1'}' -BuildOutput '{target / 'release'}' -BuildCache 'D:\\Caches\\MimoTTS\\dotnet'\nif ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}\n& '{PYTHON}' '{PROJECT / 'scripts' / 'verify_clipper_package.py'}' '{executable.parent}'\nexit $LASTEXITCODE\n")
    write(target / "Start-Test.ps1", f"$env:KNOWLEDGE_CLIPPER_ANKI_ENDPOINT='http://127.0.0.1:48991'\n$env:KNOWLEDGE_CLIPPER_REMNOTE_MCP_URL='http://127.0.0.1:48992/mcp'\nStart-Process -FilePath '{executable}' -ArgumentList '--open-settings'\n")
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--app", choices=["all", "weblilt", "anki", "openfocus", "clipper"], default="all")
    args = p.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    receipts = {}
    for name, action in [("weblilt", build_weblilt), ("anki", build_anki), ("openfocus", build_openfocus), ("clipper", prepare_clipper)]:
        if args.app in ("all", name):
            print("Packaging " + name, flush=True)
            receipts[name] = action()
            write(ROOT / (name + "-build-receipt.json"), json.dumps(receipts[name], ensure_ascii=False, indent=2))
    print(json.dumps({"root": str(ROOT), "apps": list(receipts)}))


if __name__ == "__main__":
    main()
