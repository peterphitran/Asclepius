import argparse
import json
import sys
from pathlib import Path

from live_groq_fixture import run_workflow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--evaluator", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--source-checkpoint", help="Unverified caller checkpoint metadata")
    parser.add_argument("--source-diff-sha256", help="Unverified caller diff digest metadata")
    args = parser.parse_args()
    identity = None
    if args.source_checkpoint and args.source_diff_sha256:
        identity = {"checkpoint": args.source_checkpoint, "diff_sha256": args.source_diff_sha256}
    try:
        result = run_workflow(
            args.target,
            args.evaluator,
            args.artifacts,
            interpreter=args.python,
            source_identity=identity,
        )
    except Exception:
        print(json.dumps({"status": "failed", "reason": "artifact_setup_failed"}))
        return 1
    print(
        json.dumps(
            {
                "status": result["status"],
                "reason": result.get("reason"),
                "manual_semantic_review": "pending",
            }
        )
    )
    return {"succeeded": 0, "failed": 1, "not_run": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
