import argparse
import json
from pathlib import Path

from storymap.script.profile.graph_service import sync_graph_payload_to_neo4j, write_normalized_graph_json
from storymap.script.core.project_paths import project_root_path


REPO_ROOT = project_root_path()
DEFAULT_PAYLOAD = REPO_ROOT / "artifacts" / "story_map" / "stellar_home_data.json"
DEFAULT_NORMALIZED = REPO_ROOT / "artifacts" / "graph" / "normalized_graph.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import StoryMap graph payload into Neo4j.")
    parser.add_argument("--payload", default=str(DEFAULT_PAYLOAD), help="Path to stellar_home_data.json")
    parser.add_argument(
        "--normalized-output",
        default=str(DEFAULT_NORMALIZED),
        help="Path to write the normalized graph snapshot",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to the existing StoryMap subgraph instead of replacing it",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload_path = Path(args.payload).resolve()
    normalized_path = Path(args.normalized_output).resolve()
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid graph payload: {payload_path}")
    write_normalized_graph_json(payload, normalized_path)
    synced = sync_graph_payload_to_neo4j(payload, replace=not args.append)
    if not synced:
        raise SystemExit("Neo4j is not configured or the driver is unavailable.")
    print(f"Normalized graph written to {normalized_path}")
    print(f"Neo4j import completed from {payload_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
