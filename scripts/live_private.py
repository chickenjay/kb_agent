"""Run authorized live tests without putting credentials in files or argv.

Key is read through a non-echoing terminal prompt, not a CLI option. Only
synthetic repository data is sent to the explicitly supplied model provider.
"""
import argparse
import getpass
import json
import sys
import warnings
from pathlib import Path

from kb_agent.evaluation import evaluate
from kb_agent.models import LiveModel, ModelConfig, ModelError


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--suite", choices=["basic", "advanced", "all"], default="all")
    parser.add_argument("--cases", help="Optional comma-separated trusted case IDs")
    args = parser.parse_args()
    warnings.simplefilter("error", getpass.GetPassWarning)
    secret = getpass.getpass("API key (hidden; not saved): ").strip()
    config = ModelConfig(args.base_url, secret, args.model)
    options = {"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "max_tokens": 2048, "temperature": 0}
    root = Path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    try:
        probe = LiveModel(config, request_options=options)
        action = probe.decide([{"role": "system", "content": 'Only return JSON: {"ok":true}.'}, {"role": "user", "content": "Connection check. Return the JSON object only."}])
        record = {"status": "passed", "base_url": args.base_url, "requested_model": args.model, "options": options, "metadata": probe.last_metadata, "returned_json": isinstance(action, dict)}
    except (ModelError, ValueError) as exc:
        record = {"status": "failed", "base_url": args.base_url, "requested_model": args.model, "error": str(exc).replace(secret, "[redacted]") if secret else "Missing key", "no_fallback": True}
        (root / "probe.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        return 2
    (root / "probe.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"probe": "passed", "model": args.model}, ensure_ascii=False), flush=True)
    report, directory = evaluate("live", root, suite=args.suite, model_config=config, request_options=options, case_ids=args.cases.split(",") if args.cases else None, progress=lambda event: print(json.dumps(event, ensure_ascii=False), flush=True))
    print(json.dumps({"status": report["status"], "passed": report.get("passed"), "total": report.get("total"), "report": str(directory / "summary.json")}, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    sys.exit(main())
