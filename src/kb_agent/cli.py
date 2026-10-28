import argparse
import json
import sys

from .agent import AgentRunner
from .evaluation import evaluate
from .models import ModelError
from .scenarios import faults_for, scenario_corpus
from .schemas import AskRequest


def main():
    # JSON output is UTF-8 even when Windows' legacy console locale is not.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="知据：企业知识问答 Agent（显式 Mock 或真实模型）")
    commands = parser.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask")
    ask.add_argument("--input", required=True)
    ask.add_argument("--mode", choices=["mock", "live"], required=True)
    ask.add_argument("--corpus")
    ask.add_argument("--output-dir", required=True)
    evaluation = commands.add_parser("evaluate")
    evaluation.add_argument("--mode", choices=["mock", "live"], required=True)
    evaluation.add_argument("--output-dir", required=True)
    evaluation.add_argument("--suite", choices=["basic", "advanced", "all"], default="basic")
    args = parser.parse_args()
    try:
        if args.command == "evaluate":
            report, directory = evaluate(args.mode, args.output_dir, suite=args.suite)
            print(json.dumps({"status": report["status"], "passed": report.get("passed"), "total": report.get("total"), "report": str(directory / "summary.json")}, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "passed" else 2
        from pathlib import Path
        body = json.loads(Path(args.input).read_text(encoding="utf-8"))
        body["mode"] = args.mode
        request = AskRequest.model_validate(body)
        runner = AgentRunner(request, scenario_corpus(request.scenario_id, args.corpus), faults=faults_for(request.scenario_id), output_dir=args.output_dir)
        output = runner.run()
        print(output.model_dump_json(indent=2))
        return 2 if output.status == "incomplete" else 0
    except (ValueError, OSError, ModelError) as exc:
        print(json.dumps({"error": str(exc), "mode": args.mode}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
