"""Audit the exact Git candidate set and run an offline reviewer-copy check.

Does not stage, commit, publish, or send model requests. Ignored credentials and
local dependencies are never copied into the reviewer snapshot.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "examples/verification/submission"


def git(*arguments):
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, check=True).stdout


def audit():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    started = time.monotonic()
    paths = sorted(set(p for p in git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0") if p))
    required = ["README.md", "spec.md", "submission.json", "requirements.txt", "requirements.lock.txt", "pyproject.toml", "package.json", "package-lock.json", ".env.example", "config.example.toml", *[f"docs/0{i}-{name}.md" for i, name in enumerate(("requirements", "solution", "evaluation", "ai-usage", "retrospective"), 1)]]
    problems = []
    checks = {}
    missing = sorted(set(required) - set(paths))
    if missing:
        problems.append("Missing required material: " + ", ".join(missing))
    for prefix in ("src/", "tests/", "examples/", "data/"):
        if not any(path.startswith(prefix) for path in paths):
            problems.append("Missing required non-empty directory: " + prefix)
    submission = json.loads((ROOT / "submission.json").read_text(encoding="utf-8")) if (ROOT / "submission.json").exists() else {}
    if not isinstance(submission.get("question_number"), int) or submission["question_number"] < 1:
        problems.append("Question number is not recorded")
    if not submission.get("ai_assistance") or not submission.get("personal_modifications"):
        problems.append("AI assistance or personal contribution is not recorded")
    if not submission.get("time_record") or not (ROOT / submission["time_record"]).is_file():
        problems.append("Project time record is missing")
    forbidden = [p for p in paths if p == "config.local.toml" or p.startswith((".venv/", "node_modules/", ".runtime/", ".git/")) or p == ".env"]
    if forbidden:
        problems.append("Private/runtime files in candidate set: " + ", ".join(forbidden))
    private_ignored = subprocess.run(["git", "check-ignore", "--quiet", "config.local.toml"], cwd=ROOT).returncode == 0
    if not private_ignored or git("ls-files", "--", "config.local.toml").strip():
        problems.append("Local configuration must be ignored and untracked")
    private = ROOT / "config.local.toml"
    secret = ""
    if private.exists():
        with private.open("rb") as stream:
            secret = tomllib.load(stream).get("llm", {}).get("api_key", "")
    credential_files = []
    generic_secret = re.compile(rb"(?:sk-[A-Za-z0-9]{24,}|gh[pousr]_[A-Za-z0-9]{24,})")
    total_bytes = 0
    for relative in paths:
        path = ROOT / relative
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            problems.append("Unsafe candidate path: " + relative)
            continue
        raw = path.read_bytes()
        total_bytes += len(raw)
        if (secret and secret.encode() in raw) or generic_secret.search(raw):
            credential_files.append(relative)
        if path.suffix.lower() in {".json", ".jsonl"}:
            try:
                if path.suffix == ".jsonl":
                    for line in raw.decode("utf-8-sig").splitlines():
                        if line.strip():
                            json.loads(line)
                else:
                    json.loads(raw.decode("utf-8-sig"))
            except (ValueError, UnicodeError):
                problems.append("Invalid JSON evidence: " + relative)
    if credential_files:
        problems.append("Credential-like content found; filenames only: " + ", ".join(credential_files))
    template = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    if template.get("llm", {}).get("api_key"):
        problems.append("Public config template contains a key")
    for relative in ["README.md", "spec.md", *[p for p in paths if p.startswith("docs/") and p.endswith(".md")]]:
        for target in re.findall(r"\]\(([^)]+)\)", (ROOT / relative).read_text(encoding="utf-8")):
            if target.startswith(("http:", "https:", "#")):
                continue
            destination = ((ROOT / relative).parent / target.split("#")[0]).resolve()
            if not destination.is_relative_to(ROOT) or destination.relative_to(ROOT).as_posix() not in paths:
                problems.append(f"Link absent from candidate set: {relative} -> {target}")

    runs = 0
    live_paths = set()
    for relative in paths:
        if not relative.endswith("/output.json"):
            continue
        directory = (ROOT / relative).parent
        if not (directory / "trace.jsonl").exists() or not (directory / "input.json").exists():
            problems.append("Incomplete run evidence: " + relative)
            continue
        output = json.loads((directory / "output.json").read_text(encoding="utf-8"))
        events = [json.loads(line) for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        if not events or events[-1]["event"] != "final" or sum(e["event"] == "final" for e in events) != 1:
            problems.append("Invalid final event: " + relative)
            continue
        if events[-1]["payload"]["output"] != output:
            problems.append("Saved output differs from actual final event: " + relative)
        if [e["seq"] for e in events] != list(range(1, len(events) + 1)) or {e["run_id"] for e in events} != {output["run_id"]}:
            problems.append("Trace sequence/run identity mismatch: " + relative)
        if events[-1]["payload"]["decisions"] > 8 or events[-1]["payload"]["tool_calls"] > 6:
            problems.append("Execution budget exceeded: " + relative)
        evidence = {}
        for event in events:
            if event["event"] == "tool_result" and event["payload"]["ok"] and event["payload"]["tool"] == "read_snippet":
                row = event["payload"]["observation"]["data"]
                evidence[(row["document_id"], row["snippet_id"])] = row
        for citation in output["citations"]:
            row = evidence.get((citation["document_id"], citation["snippet_id"]))
            if row is None or citation["quote"] not in row["text"] or citation["version_date"] != row["version_date"]:
                problems.append("Citation not supported by a successful read: " + relative)
        if output["mode"] == "live":
            live_paths.add(tuple(e["payload"]["action"] for e in events if e["event"] == "action"))
        runs += 1
    if len(live_paths) < 2:
        problems.append("Fewer than two distinct real-model execution paths")
    checks.update(candidate_files=len(paths), total_bytes=total_bytes, local_config_ignored=private_ignored, credential_like_files=credential_files, evidence_runs_checked=runs, distinct_live_action_paths=len(live_paths))
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    if problems:
        report = {"status": "failed", "checks": checks, "problems": problems}
        (REPORT_DIR / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    snapshot = ROOT / ".runtime" / ("submission-review-" + stamp)
    snapshot.mkdir(parents=True)
    for relative in paths:
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    assert not (snapshot / "config.local.toml").exists()
    environment = dict(os.environ)
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        environment.pop(name, None)
    environment.update(PYTHONPATH=str(snapshot / "src"), PYTHONIOENCODING="utf-8")
    # Prove imports originate from the copied candidate set, not our editable install.
    code = "from pathlib import Path; import kb_agent; from kb_agent.models import ModelConfig; assert Path(kb_agent.__file__).resolve().is_relative_to(Path.cwd()); assert not ModelConfig.from_env().configured; print('isolated source imports; no private model configuration')"
    commands = [("snapshot-import", [sys.executable, "-c", code]), ("snapshot-python-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]), ("snapshot-mock-evaluation", [sys.executable, "-m", "kb_agent", "evaluate", "--mode", "mock", "--suite", "all", "--output-dir", ".runtime/evaluation"])]
    node = shutil.which("node")
    if node:
        commands.append(("snapshot-frontend-tests", [node, "--test", *[str(p.relative_to(snapshot)) for p in sorted((snapshot / "tests/frontend").glob("*.test.mjs"))]]))
    results = []
    for name, command in commands:
        process = subprocess.run(command, cwd=snapshot, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        (REPORT_DIR / (name + ".txt")).write_text(process.stdout + process.stderr, encoding="utf-8")
        results.append({"name": name, "passed": process.returncode == 0, "output": name + ".txt"})
        if process.returncode:
            problems.append("Reviewer snapshot check failed: " + name)
    if not node:
        problems.append("Node unavailable; frontend checks not run")
    source_hash = hashlib.sha256()
    for relative in paths:
        if relative.startswith(("src/", "tests/", "data/", "web/")):
            source_hash.update(relative.encode() + b"\0" + (ROOT / relative).read_bytes())
    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "status": "passed" if not problems else "failed", "scope": "Exact Git candidate set; private credentials and local dependencies excluded; offline reviewer snapshot; no paid model calls", "checks": checks, "submission_info": submission, "source_sha256": source_hash.hexdigest(), "reviewer_snapshot_checks": results, "elapsed_seconds": round(time.monotonic() - started, 3), "problems": problems, "candidate_confirmations_pending": ["本人逐例语义复核（自动检查不替代人工）"]}
    (REPORT_DIR / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(audit())
