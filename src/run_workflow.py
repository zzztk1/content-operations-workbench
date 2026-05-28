import argparse
import json

from agent_graph import MediaAgentGraph


def main() -> None:
    parser = argparse.ArgumentParser(description="Run media-agent workflow from CLI")
    parser.add_argument("--brief", required=True, help="content brief")
    parser.add_argument("--platform", default="小红书", help="target platform")
    parser.add_argument("--style", default="种草推荐", help="content style")
    parser.add_argument("--approval", default="approve", choices=["approve", "needs_edit", "reject"])
    parser.add_argument("--threshold", type=int, default=21, help="review pass threshold")
    parser.add_argument("--max-revisions", type=int, default=2, help="max rewrite loops")
    args = parser.parse_args()

    engine = MediaAgentGraph()
    result = engine.run_workflow(
        brief=args.brief,
        platform=args.platform,
        style=args.style,
        approval_decision=args.approval,
        reviewer_threshold=args.threshold,
        max_revisions=args.max_revisions,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
