from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

file_path = Path(__file__).resolve()
REPO_ROOT = file_path.parents[2] if file_path.parent.name == "extras" else file_path.parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import offline_eval
from project_paths import data_corpus_file_path, data_reports_output_path
import story_agents


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="离线评估 Agent 生成人物 Markdown 的准确率")
    parser.add_argument("--people", nargs="*", default=[], help="要评估的人物列表，例如：李白 杜甫")
    parser.add_argument(
        "--people-file",
        default=str(data_corpus_file_path("pep_history_figures_sample.json", project_root=REPO_ROOT)),
        help="人物基准列表文件，默认为 data/corpus/pep_history_figures_sample.json",
    )
    parser.add_argument("--limit", type=int, default=3, help="最多评估多少个人物")
    parser.add_argument(
        "--output-json",
        default=str(data_reports_output_path("offline_agent_eval_report.json", project_root=REPO_ROOT)),
        help="评估报告输出路径",
    )
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    people = offline_eval.load_benchmark_people(
        people=args.people,
        people_file=args.people_file,
        limit=args.limit,
        root=REPO_ROOT,
    )
    if not people:
        print("未找到可评估的人物样本。")
        return 1
    client = story_agents.StoryAgentLLM()
    report = offline_eval.evaluate_people(
        people=people,
        generate_markdown=lambda person: story_agents.generate_historical_markdown(client, person) or "",
        postprocess_markdown=offline_eval.enrich_markdown_for_evaluation,
        root=REPO_ROOT,
    )
    out = offline_eval.write_report(report, args.output_json)
    summary = {
        "count": report.get("count"),
        "weighted_accuracy": report.get("aggregate", {}).get("weighted_accuracy"),
        "scores": report.get("aggregate", {}).get("scores", {}),
        "output": out,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
