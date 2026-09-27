"""Verify this project contains no configured key and inspect packaging inputs."""
import hashlib
import json
import subprocess
from pathlib import Path
from mimo_tts.client import credential

root = Path(__file__).resolve().parents[1]
names = subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).decode().split("\0")
key, _ = credential()
key_bytes = key.encode()
for name in names:
    if name and (root / name).is_file():
        if key_bytes in (root / name).read_bytes():
            raise SystemExit("Configured key was found in project files; upload blocked")
print(json.dumps({"credential_scan": "PASS", "files": sum(bool(x) for x in names)}))

receipts = Path(r"D:\Artifacts\MimoTTS\test-builds").glob("*-build-receipt.json")
results = []
for path in receipts:
    receipt = json.loads(path.read_text(encoding="utf-8"))
    source = Path(receipt["source"])
    changed = []
    for relative, expected in receipt["files"].items():
        original = source / relative
        if not original.exists() or hashlib.sha256(original.read_bytes()).hexdigest() != expected:
            changed.append(relative)
    results.append({"app": path.name.removesuffix("-build-receipt.json"), "source_files_compared": len(receipt["files"]), "changes_since_snapshot": changed})
print(json.dumps({"source_comparison": results}, ensure_ascii=False))
