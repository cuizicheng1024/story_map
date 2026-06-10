from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_agents


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="检查大模型接口连通性与稳定性")
    parser.add_argument("--attempts", type=int, default=1, help="健康检查调用次数")
    parser.add_argument("--prompt", default="请只回复 OK", help="用于健康检查的短提示词")
    parser.add_argument("--temperature", type=float, default=0.0, help="采样温度")
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    client = story_agents.StoryAgentLLM()
    report = client.check_health(
        prompt=args.prompt,
        attempts=max(1, int(args.attempts)),
        temperature=float(args.temperature),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
