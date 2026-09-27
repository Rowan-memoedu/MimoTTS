"""Create a factual build inventory, then run the application's verifier."""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1]).resolve()
expected = Path(r"D:\Artifacts\MimoTTS\test-builds\KnowledgeClipper").resolve()
production = Path(r"D:\Artifacts\MimoTTS\production\20260927\KnowledgeClipper").resolve()
if expected not in root.parents and production not in root.parents:
    raise SystemExit("Refusing inventory outside a known MiMo delivery directory")
if production in root.parents:
    expected = production
files = []
for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
    if path.is_file() and path.name != "desktop-build-receipt.v1.json":
        files.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
material = "".join(f"{r['path']}\n{r['sha256']}\n{r['bytes']}\n" for r in files)
receipt = {"schemaVersion": "mimo-desktop-inventory.v1", "generatedAt": datetime.now(timezone.utc).isoformat(), "files": files, "fileCount": len(files), "totalBytes": sum(r["bytes"] for r in files), "treeSha256": hashlib.sha256(material.encode()).hexdigest()}
(root / "desktop-build-receipt.v1.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
run = subprocess.run([root / "KnowledgeClipper.exe", "--startup-diagnostic"], capture_output=True, text=True, encoding="utf-8", timeout=60)
report = json.loads(run.stdout)
evidence = expected / ("startup-diagnostic-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
evidence.write_text(run.stdout, encoding="utf-8")
print(json.dumps({"exit_code": run.returncode, "result": report["result"], "verified_files": report["packageFileCount"], "work_directory": report["workDirectory"], "existing_instance": report["singleInstanceAlreadyRunning"], "external_connections": report["externalConnections"], "evidence": str(evidence), "failures": report["failures"]}))
raise SystemExit(run.returncode)
