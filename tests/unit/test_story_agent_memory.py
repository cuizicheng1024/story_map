import sys
import time
import json


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storymap.script.runtime.legacy_agent import graph as story_agent_graph
from storymap.script.runtime.legacy_agent import memory as story_agent_memory


def test_story_agent_memory_store_persists_search_and_place_data(tmp_path):
    path = tmp_path / "story_agent_memory.json"
    store = story_agent_memory.StoryAgentMemoryStore(str(path))
    store.set_person_search("李白", {"person": "李白", "summary": "唐代诗人"})
    store.set_place_map("碎叶城", {"query": "碎叶城", "modern_name": "托克马克"})

    reloaded = story_agent_memory.StoryAgentMemoryStore(str(path))

    assert reloaded.get_person_search("李白") == {"person": "李白", "summary": "唐代诗人"}
    assert reloaded.get_place_map("碎叶城") == {"query": "碎叶城", "modern_name": "托克马克"}


def test_story_markdown_agent_reuses_persisted_memory_across_agent_instances(tmp_path):
    calls = []
    path = tmp_path / "story_agent_memory.json"

    def _search(person_name: str):
        calls.append(f"search:{person_name}")
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [],
            "places": [],
            "cautions": [],
        }

    store_a = story_agent_memory.StoryAgentMemoryStore(str(path))
    agent_a = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=lambda structure: f"# {structure.get('person')}\n",
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=2,
        memory_store=store_a,
    )
    first = agent_a["run"]("李白", 0, agent_a["max_llm_calls"])

    store_b = story_agent_memory.StoryAgentMemoryStore(str(path))
    agent_b = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=lambda structure: f"# {structure.get('person')}\n",
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=2,
        memory_store=store_b,
    )
    second = agent_b["run"]("李白", 0, agent_b["max_llm_calls"])

    assert first["markdown"] == "# 李白\n"
    assert second["markdown"] == "# 李白\n"
    assert calls == ["search:李白"]


def test_story_agent_memory_store_expires_entries_by_ttl(tmp_path):
    path = tmp_path / "story_agent_memory.json"
    payload = {
        "schema_version": story_agent_memory.DEFAULT_MEMORY_SCHEMA_VERSION,
        "people": {
            "李白": {
                "search_result": {"person": "李白", "summary": "唐代诗人"},
                "updated_at": time.time() - 120,
            }
        },
        "places": {},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    store = story_agent_memory.StoryAgentMemoryStore(str(path), ttl_seconds=60)

    assert store.get_person_search("李白") is None


def test_story_agent_memory_store_invalidates_specific_entries(tmp_path):
    path = tmp_path / "story_agent_memory.json"
    store = story_agent_memory.StoryAgentMemoryStore(str(path))
    store.set_person_search("李白", {"person": "李白", "summary": "唐代诗人"})
    store.set_place_map("碎叶城", {"query": "碎叶城", "modern_name": "托克马克"})

    assert store.invalidate_person_search("李白") is True
    assert store.invalidate_place_map("碎叶城") is True

    reloaded = story_agent_memory.StoryAgentMemoryStore(str(path))
    assert reloaded.get_person_search("李白") is None
    assert reloaded.get_place_map("碎叶城") is None


def test_story_agent_memory_store_ignores_old_schema_and_rewrites_new_payload(tmp_path):
    path = tmp_path / "story_agent_memory.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": story_agent_memory.DEFAULT_MEMORY_SCHEMA_VERSION - 1,
                "people": {
                    "李白": {
                        "search_result": {"person": "李白", "summary": "旧缓存"},
                        "updated_at": time.time(),
                    }
                },
                "places": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = story_agent_memory.StoryAgentMemoryStore(str(path))

    assert store.get_person_search("李白") is None
    store.set_person_search("杜甫", {"person": "杜甫", "summary": "唐代诗人"})

    reloaded_payload = json.loads(path.read_text(encoding="utf-8"))
    assert reloaded_payload["schema_version"] == story_agent_memory.DEFAULT_MEMORY_SCHEMA_VERSION
    assert "李白" not in reloaded_payload["people"]
    assert reloaded_payload["people"]["杜甫"]["search_result"]["person"] == "杜甫"
