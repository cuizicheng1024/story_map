import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import story_agent_graph
import story_agents
import story_agent_memory


def test_create_agent_tools_expose_expected_names():
    tools = story_agent_graph.create_agent_tools(
        search_person_info_fn=lambda person_name: {
            "person": person_name,
            "summary": "",
            "identities": [],
            "achievements": [],
            "timeline": [],
            "places": [],
            "cautions": [],
        },
        fetch_ancient_place_map_fn=lambda place_name: {
            "query": place_name,
            "ancient_name": place_name,
            "modern_name": place_name,
            "lat": None,
            "lng": None,
            "source": "",
        },
        generate_markdown_fn=lambda structure: str(structure.get("person") or ""),
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
    )

    assert {item.__tool__.name for item in tools.values()} == {
        "search_person_info",
        "fetch_ancient_place_map",
        "generate_markdown",
        "validate_markdown",
    }
    assert tools["search_person_info"].__tool__.retry_count == 2
    assert tools["generate_markdown"].__tool__.timeout_seconds == 60.0


def test_story_markdown_agent_revises_after_critic_feedback():
    calls = []
    editor_structures = []

    def _search(person_name: str):
        calls.append(f"search:{person_name}")
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [{"year": "701年", "event": "出生", "place": "碎叶城"}],
            "places": [{"name": "碎叶城", "context": "出生地"}],
            "cautions": [],
        }

    def _map(place_name: str):
        calls.append(f"map:{place_name}")
        return {
            "query": place_name,
            "ancient_name": "碎叶城",
            "modern_name": "吉尔吉斯斯坦托克马克",
            "lat": 42.84,
            "lng": 75.29,
            "source": "test",
        }

    def _generate(structure):
        calls.append("edit")
        editor_structures.append(structure)
        feedback = structure.get("critic_feedback") or []
        if feedback:
            return (
                "# 人物 生平传记与足迹\n\n"
                "## 一、人物档案\n\n"
                "### 基本信息\n"
                "- **姓名**：李白\n"
                "- **时代**：唐朝\n"
                "- **出生**：701年，碎叶城（今吉尔吉斯斯坦托克马克）\n"
                "- **去世**：762年，安徽当涂\n"
                "- **享年**：61岁\n"
                "- **主要身份**：诗人\n"
                "- **历史地位**：浪漫主义诗歌代表\n"
                "- **主要成就**：诗歌创作\n\n"
                "### 生平概述\n李白，唐代诗人。\n\n"
                "## 四、生平时间线\n\n"
                "| 年份 | 古称 | 现称 | 事件 |\n"
                "| --- | --- | --- | --- |\n"
                "| 701年 | 碎叶城 | 吉尔吉斯斯坦托克马克 | 出生 |\n"
                "| 762年 | 当涂 | 安徽马鞍山当涂县 | 去世 |\n"
            )
        return (
            "# 人物 生平传记与足迹\n\n"
            "## 一、人物档案\n\n"
            "### 基本信息\n"
            "- **姓名**：李白\n"
            "- **时代**：唐朝\n"
            "- **出生**：701年，碎叶城\n"
            "- **去世**：762年，安徽当涂\n"
            "- **享年**：61岁\n"
            "- **主要身份**：诗人\n"
            "- **历史地位**：浪漫主义诗歌代表\n"
            "- **主要成就**：诗歌创作\n\n"
            "### 生平概述\n李白，唐代诗人。\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 701年 | 碎叶城 |  | 出生 |\n"
            "| 762年 | 当涂 | 安徽马鞍山当涂县 | 去世 |\n"
        )

    def _validate(content: str):
        calls.append("critic")
        if "吉尔吉斯斯坦托克马克" not in content:
            return {
                "pass": False,
                "risk_level": "medium",
                "issues": [
                    {
                        "field": "location",
                        "claim": "碎叶城",
                        "correction": "碎叶城（今吉尔吉斯斯坦托克马克）",
                        "confidence": 0.82,
                        "reason": "出生地缺少现代城市名",
                    }
                ],
                "notes": "地点仍不够精确",
            }
        return {"pass": True, "risk_level": "low", "issues": [], "notes": ""}

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        fetch_ancient_place_map_fn=_map,
        generate_markdown_fn=_generate,
        validate_markdown_fn=_validate,
    )

    result = agent["run"]("李白", 1)

    assert "吉尔吉斯斯坦托克马克" in result["markdown"]
    assert result["state"]["revision_count"] == 1
    assert result["state"]["validation"]["pass"] is True
    assert result["state"]["execution_trace"].count("critic_agent") == 2
    assert len(result["state"]["tool_traces"]) == 7
    assert all("tool_name" in item for item in result["state"]["tool_traces"])
    assert editor_structures[0]["runtime_reflection"]["tool_summary"]["total_calls"] >= 1
    assert "运行时反思" in editor_structures[0]["runtime_reflection_prompt"]
    assert editor_structures[1]["runtime_reflection"]["retry_summary"]["revision_count"] == 1
    assert calls == [
        "search:李白",
        "map:碎叶城",
        "edit",
        "critic",
        "map:碎叶城",
        "edit",
        "critic",
    ]


def test_generate_historical_markdown_prefers_agent_workflow(monkeypatch):
    class DummyLLM:
        def think(self, _messages, temperature=0):
            return f"legacy-{temperature}"

        def _emit(self, _message):
            return None

    monkeypatch.setattr(
        story_agents.story_agent_graph_utils,
        "generate_markdown_with_agents",
        lambda _llm, _person: {"markdown": "agent-markdown"},
    )

    assert story_agents.generate_historical_markdown(DummyLLM(), "李白") == "agent-markdown"


def test_generate_historical_markdown_falls_back_to_legacy(monkeypatch):
    class DummyLLM:
        def think(self, _messages, temperature=0):
            _ = temperature
            return "legacy-markdown"

        def _emit(self, _message):
            return None

    monkeypatch.setattr(
        story_agents.story_agent_graph_utils,
        "generate_markdown_with_agents",
        lambda _llm, _person: {"markdown": ""},
    )

    assert story_agents.generate_historical_markdown(DummyLLM(), "李白") == "legacy-markdown"


def test_story_markdown_agent_uses_fallback_markdown_when_llm_budget_exhausted():
    calls = []

    def _search(person_name: str):
        calls.append(f"search:{person_name}")
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [{"year": "701年", "event": "出生", "place": "碎叶城"}],
            "places": [{"name": "碎叶城", "context": "出生地"}],
            "cautions": [],
        }

    def _generate(_structure):
        calls.append("edit")
        return "SHOULD_NOT_BE_USED"

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=_generate,
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=0,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert "## 一、人物档案" in result["markdown"]
    assert "## 三、人生历程与重要地点（按时间顺序）" in result["markdown"]
    assert "暂无可用时间线资料" in result["markdown"]
    assert calls == []
    assert result["state"]["llm_calls_used"] == 0
    assert any("LLM_CALL_BUDGET_EXCEEDED" in item for item in result["state"]["degraded_reasons"])


def test_story_markdown_agent_falls_back_when_editor_raises():
    def _search(person_name: str):
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [{"year": "701年", "event": "出生", "place": "碎叶城"}],
            "places": [{"name": "碎叶城", "context": "出生地"}],
            "cautions": ["出生地有不同说法"],
        }

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        fetch_ancient_place_map_fn=lambda place_name: {
            "query": place_name,
            "ancient_name": place_name,
            "modern_name": "吉尔吉斯斯坦托克马克",
            "lat": 42.84,
            "lng": 75.29,
            "source": "test",
        },
        generate_markdown_fn=lambda _structure: (_ for _ in ()).throw(RuntimeError("editor boom")),
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=3,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert "吉尔吉斯斯坦托克马克" in result["markdown"]
    assert "- **时代**：唐代" in result["markdown"]
    assert "| 701年 | 碎叶城 | 吉尔吉斯斯坦托克马克 | 出生 |" in result["markdown"]
    assert any("editor_agent:editor boom" in item for item in result["state"]["degraded_reasons"])


def test_story_markdown_agent_counts_failed_search_call_against_budget():
    calls = []

    def _search(_person_name: str):
        calls.append("search")
        raise RuntimeError("search boom")

    def _generate(_structure):
        calls.append("edit")
        return "SHOULD_NOT_BE_USED"

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=_generate,
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=1,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert calls == ["search", "search", "search"]
    assert result["state"]["llm_calls_used"] == 1
    assert any("search_agent:search boom" in item for item in result["state"]["degraded_reasons"])
    assert any("editor_agent:LLM_CALL_BUDGET_EXCEEDED:1/1" in item for item in result["state"]["degraded_reasons"])
    assert "降级整理稿" in result["markdown"]


def test_story_markdown_agent_falls_back_when_critic_raises():
    calls = []

    def _search(person_name: str):
        calls.append("search")
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [
                {"year": "701年", "event": "出生", "place": "碎叶城"},
                {"year": "762年", "event": "去世", "place": "当涂"},
            ],
            "places": [{"name": "碎叶城", "context": "出生地"}],
            "cautions": [],
        }

    def _generate(_structure):
        calls.append("edit")
        return (
            "# 人物 生平传记与足迹\n\n"
            "## 一、人物档案\n\n"
            "### 基本信息\n"
            "- **姓名**：李白\n"
            "- **时代**：唐朝\n"
            "- **出生**：701年，碎叶城\n"
            "- **去世**：762年，当涂\n"
            "- **享年**：61岁\n"
            "- **主要身份**：诗人\n"
            "- **历史地位**：浪漫主义诗歌代表\n"
            "- **主要成就**：诗歌创作\n\n"
            "### 生平概述\n李白，唐代诗人。\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 701年 | 碎叶城 |  | 出生 |\n"
            "| 762年 | 当涂 |  | 去世 |\n"
        )

    def _validate(_content: str):
        calls.append("critic")
        raise RuntimeError("critic boom")

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=_generate,
        validate_markdown_fn=_validate,
        max_llm_calls=4,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert calls == ["search", "edit", "critic"]
    assert result["markdown"]
    assert result["state"]["final_markdown"] == result["markdown"]
    assert any("critic_agent:critic boom" in item for item in result["state"]["degraded_reasons"])
    assert "issues" in result["state"]["validation"]


def test_story_markdown_agent_stops_after_max_revisions():
    calls = []

    def _search(person_name: str):
        calls.append("search")
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [{"year": "701年", "event": "出生", "place": "碎叶城"}],
            "places": [{"name": "碎叶城", "context": "出生地"}],
            "cautions": [],
        }

    def _map(place_name: str):
        calls.append("map")
        return {
            "query": place_name,
            "ancient_name": place_name,
            "modern_name": "吉尔吉斯斯坦托克马克",
            "lat": 42.84,
            "lng": 75.29,
            "source": "test",
        }

    def _generate(_structure):
        calls.append("edit")
        return (
            "# 人物 生平传记与足迹\n\n"
            "## 一、人物档案\n\n"
            "### 基本信息\n"
            "- **姓名**：李白\n"
            "- **时代**：唐朝\n"
            "- **出生**：701年，碎叶城\n"
            "- **主要身份**：诗人\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 701年 | 碎叶城 |  | 出生 |\n"
        )

    def _validate(_content: str):
        calls.append("critic")
        return {
            "pass": False,
            "risk_level": "medium",
            "issues": [
                {
                    "field": "location",
                    "claim": "碎叶城",
                    "correction": "碎叶城（今吉尔吉斯斯坦托克马克）",
                    "confidence": 0.9,
                    "reason": "地点仍不够精确",
                }
            ],
            "notes": "仍需修订",
        }

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        fetch_ancient_place_map_fn=_map,
        generate_markdown_fn=_generate,
        validate_markdown_fn=_validate,
        max_llm_calls=6,
    )

    result = agent["run"]("李白", 1, agent["max_llm_calls"])

    assert calls == ["search", "map", "edit", "critic", "map", "edit", "critic"]
    assert result["state"]["revision_count"] == 1
    assert result["state"]["needs_revision"] is False
    assert result["state"]["execution_trace"].count("critic_agent") == 2
    assert result["markdown"]


def test_story_markdown_agent_reuses_cached_search_result_across_runs(tmp_path):
    calls = []
    store = story_agent_memory.StoryAgentMemoryStore(str(tmp_path / "story_agent_memory.json"))

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

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=lambda structure: f"# {structure.get('person')}\n",
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=2,
        memory_store=store,
    )

    first = agent["run"]("李白", 0, agent["max_llm_calls"])
    second = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert first["markdown"] == "# 李白\n"
    assert second["markdown"] == "# 李白\n"
    assert calls == ["search:李白"]
    assert first["state"]["memory_hits"] == {}
    assert first["state"]["memory_misses"] == {"search": 1}
    assert second["state"]["memory_hits"] == {"search": 1}
    assert second["state"]["memory_misses"] == {}
    assert any(item.get("memory_bucket") == "search" and item.get("memory_hit") is True for item in second["state"]["tool_traces"])


def test_story_markdown_agent_maps_all_deduped_places_without_top10_truncation():
    mapped = []
    place_names = [f"地点{i}" for i in range(12)]

    def _search(person_name: str):
        return {
            "person": person_name,
            "summary": "测试人物",
            "identities": ["人物"],
            "achievements": ["测试"],
            "timeline": [{"year": "1年", "event": "事件", "place": place_names[0]}],
            "places": [{"name": name, "context": f"事件{name}"} for name in place_names],
            "cautions": [],
        }

    def _map(place_name: str):
        mapped.append(place_name)
        return {
            "query": place_name,
            "ancient_name": place_name,
            "modern_name": place_name,
            "lat": 1.0,
            "lng": 1.0,
            "source": "test",
        }

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        fetch_ancient_place_map_fn=_map,
        generate_markdown_fn=lambda structure: f"# {structure.get('person')}\n",
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=4,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert result["markdown"] == "# 李白\n"
    assert mapped == place_names
    assert len(result["state"]["place_maps"]) == 12


def test_story_markdown_agent_reuses_cached_place_map_across_runs(tmp_path):
    calls = []
    store = story_agent_memory.StoryAgentMemoryStore(str(tmp_path / "story_agent_memory.json"))

    def _search(person_name: str):
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [{"year": "701年", "event": "出生", "place": "碎叶城"}],
            "places": [{"name": "碎叶城", "context": "出生地"}],
            "cautions": [],
        }

    def _map(place_name: str):
        calls.append(f"map:{place_name}")
        return {
            "query": place_name,
            "ancient_name": place_name,
            "modern_name": "吉尔吉斯斯坦托克马克",
            "lat": 42.84,
            "lng": 75.29,
            "source": "test",
        }

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        fetch_ancient_place_map_fn=_map,
        generate_markdown_fn=lambda structure: f"# {structure.get('person')}\n",
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=2,
        memory_store=store,
    )

    first = agent["run"]("李白", 0, agent["max_llm_calls"])
    second = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert first["markdown"] == "# 李白\n"
    assert second["markdown"] == "# 李白\n"
    assert calls == ["map:碎叶城"]
    assert first["state"]["memory_hits"] == {}
    assert first["state"]["memory_misses"] == {"search": 1, "place_map": 1}
    assert second["state"]["memory_hits"] == {"search": 1, "place_map": 1}
    assert second["state"]["memory_misses"] == {}
    assert any(item.get("memory_bucket") == "place_map" and item.get("memory_hit") is True for item in second["state"]["tool_traces"])
