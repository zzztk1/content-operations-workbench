import argparse
import json
import sys

from langgraph_v2 import LangGraphMediaAgentEngine


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run media-agent LangGraph v2 workflow from CLI")
    parser.add_argument("--brief", required=True, help="content brief")
    parser.add_argument("--platform", default="小红书", help="target platform")
    parser.add_argument("--style", default="种草推荐", help="content style")
    parser.add_argument("--approval", default="approve", choices=["approve", "needs_edit", "reject"])
    parser.add_argument("--threshold", type=int, default=21, help="review pass threshold")
    parser.add_argument("--max-revisions", type=int, default=2, help="max rewrite loops")
    parser.add_argument("--run-id", default="", help="optional run identifier")
    args = parser.parse_args()

    with LangGraphMediaAgentEngine() as engine:
        result = engine.run_workflow(
            brief=args.brief,
            platform=args.platform,
            style=args.style,
            approval_decision=args.approval,
            reviewer_threshold=args.threshold,
            max_revisions=args.max_revisions,
            run_id=args.run_id or None,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
