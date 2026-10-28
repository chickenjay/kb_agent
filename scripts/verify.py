"""Save actual test outputs, retaining previous runs. Run from the source repo."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "examples/verification"
    if (directory / "summary.json").exists():
        directory /= datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, exist_ok=True)
    node = shutil.which("node")
    commands = [("python-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]), ("dependency-check", [sys.executable, "-m", "pip", "check"])]
    if node:
        commands.append(("frontend-tests", [node, "--test", *[str(p.relative_to(ROOT)) for p in sorted((ROOT / "tests/frontend").glob("*.test.mjs"))]]))
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    results = []
    for name, command in commands:
        start = time.monotonic()
        process = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        output = process.stdout + process.stderr
        (directory / f"{name}.txt").write_text(output, encoding="utf-8")
        count = re.search(r"Ran (\d+) tests", output) if name == "python-tests" else re.search(r"(?:#|ℹ) tests (\d+)", output)
        results.append({"name": name, "exit_code": process.returncode, "tests": int(count[1]) if count else None, "elapsed_seconds": round(time.monotonic() - start, 3), "output": f"{name}.txt"})
    summary = {"generated_at": datetime.now(timezone.utc).isoformat(), "scope": "automated tests and dependency integrity; NOT live model evaluation", "checks": results, "status": "passed" if all(r["exit_code"] == 0 for r in results) and node else "failed"}
    (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    pointer = {"summary": (directory / "summary.json").relative_to(ROOT / "examples/verification").as_posix(), "status": summary["status"], "checks": results}
    (ROOT / "examples/verification/latest.json").write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
