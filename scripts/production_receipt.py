"""Record source baselines and verify unrelated files survive a provider-only merge."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(r"D:\Artifacts\MimoTTS\production\20260927")
PROJECTS = {
    "WebLilt": Path(r"D:\Projects\WebLilt"),
    "KnowledgeClipper": Path(r"D:\Projects\RemNote Quick Clipper"),
    "Anki": Path(r"D:\Projects\SuperFreeTTSReview"),
    "OpenFocus": Path(r"D:\Projects\OpenFocus"),
    "SpeechKit": Path(r"D:\Workspaces\新建文件夹\04 Projects\Personal Tool Technology Control\speech-kit"),
}

def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args]).decode("utf-8").strip()

def hashes(root):
    paths = subprocess.check_output(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."]).decode("utf-8").split("\0")
    result = {}
    for relative in paths:
        path = root / relative
        if relative and path.is_file() and not path.is_symlink():
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["baseline", "verify"])
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    baseline = ROOT / "source-baseline.json"
    if args.operation == "baseline":
        if baseline.exists():
            raise RuntimeError("Baseline already exists; never overwrite original evidence")
        records = {name: dict(path=str(root), head=git(root, "rev-parse", "HEAD"), status=git(root, "status", "--short", "--", "."), files=hashes(root)) for name, root in PROJECTS.items()}
        baseline.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print("BASELINE RECORDED", baseline)
    else:
        original = json.loads(baseline.read_text(encoding="utf-8"))
        report = {}
        for name, root in PROJECTS.items():
            before = original[name]["files"]
            after = hashes(root)
            changed = [p for p in before if after.get(p) != before[p]]
            report[name] = dict(baseline_head=original[name]["head"], current_head=git(root, "rev-parse", "HEAD"), changed=changed, added=sorted(set(after)-set(before)), unchanged_count=sum(after.get(p)==h for p,h in before.items()), missing=[p for p in before if p not in after])
        (ROOT / "source-merge-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
