import json
from typing import Optional

import pytest

from storymap.script.runtime.legacy_agent import graph as story_agent_graph
from storymap.script.agent import registry as story_agents
from storymap.script.runtime.legacy_agent import memory as story_agent_memory
from storymap.script.runtime.legacy_agent import state as story_agent_state
from storymap.script.runtime.legacy_agent import tool_runner as story_agent_tool_runner

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
        "queue_hard_place_review",
        "generate_markdown",
        "validate_markdown",
    }
    assert tools["search_person_info"].__tool__.retry_count == 2
    assert tools["search_person_info"].__tool__.timeout_seconds == 60.0
    assert tools["generate_markdown"].__tool__.timeout_seconds == 120.0
    assert tools["generate_markdown"].__tool__.retry_count == 1
    assert "llm" not in tools["search_person_info"].__tool__.tags
    assert tools["generate_markdown"].__tool__.permission == "read"
    assert "llm" not in tools["generate_markdown"].__tool__.tags

def test_queue_hard_place_review_tool_writes_and_dedupes_queue(tmp_path, monkeypatch):
    queue_path = tmp_path / "data" / "runtime" / "hard_place_review_queue.json"
    monkeypatch.setenv("STORY_HARD_PLACE_QUEUE_JSON", str(queue_path))

    tools = story_agent_graph.create_agent_tools()

    first = tools["queue_hard_place_review"](
        {
            "place_name": "碎叶城",
            "person": "李白",
            "context": "出生地待解析",
            "reason": "agent_test",
        }
    )
    second = tools["queue_hard_place_review"](
        {
            "place_name": "碎叶城",
            "person": "李白",
            "context": "出生地待解析",
            "reason": "agent_test",
        }
    )

    payload = json.loads(queue_path.read_text(encoding="utf-8"))

    assert first["status"] == "queued"
    assert second["status"] == "already_queued"
    assert first["queued"] is True
    assert payload["summary"]["items"] == 1
    assert payload["summary"]["agent_submitted"] == 1
    assert payload["items"][0]["raw_place"] == "碎叶城"
    assert payload["items"][0]["sources"]["agent_submissions"] == 2
    assert payload["items"][0]["recommended_search_name"] == "碎叶城"
    assert any(
        ref.get("person") == "李白" and ref.get("snippet") == "出生地待解析"
        for ref in payload["items"][0]["references"]
    )

def test_fetch_ancient_place_map_auto_queues_unresolved_place(tmp_path, monkeypatch):
    class FakeGeocodeService:
        @staticmethod
        def split_ancient_modern(loc_text: str, event_callback=None):
            _ = event_callback
            return loc_text, ""

        @staticmethod
        def lookup_coords_from_historical_index(*_names: str, dynasty: Optional[str] = None):
            return None

        @staticmethod
        def resolve_place_coord(_place: str, _year=None, *_aliases: str, dynasty: Optional[str] = None):
            return None

        @staticmethod
        def normalize_place_key(text: str) -> str:
            return str(text or "").strip()

    queue_path = tmp_path / "data" / "runtime" / "hard_place_review_queue.json"
    monkeypatch.setenv("STORY_HARD_PLACE_QUEUE_JSON", str(queue_path))
    monkeypatch.setattr(story_agent_graph, "_geocode_service_utils", lambda: FakeGeocodeService())

    tools = story_agent_graph.create_agent_tools()
    result = tools["fetch_ancient_place_map"]("碎叶城")
    payload = json.loads(queue_path.read_text(encoding="utf-8"))

    assert result["lat"] is None
    assert result["lng"] is None
    assert result["source"] == ""
    assert result["review_queued"] is True
    assert result["review_status"] == "queued"
    assert result["review_item_id"] == "碎叶城"
    assert result["review_reason"] == "geocode_failed"
    assert result["review_target"] == str(queue_path)
    assert payload["items"][0]["raw_place"] == "碎叶城"
    assert payload["items"][0]["evidence"] == ["agent_geocode_fallback", "geocode_failed"]

def test_create_agent_tools_marks_validator_as_llm_optional_when_fact_check_enabled(monkeypatch):
    class DummyLLM:
        def think(self, _messages, temperature=0):
            _ = temperature
            return '{"issues":[]}'

    monkeypatch.setenv("STORY_AGENT_ENABLE_FACT_CHECK_LLM", "1")

    tools = story_agent_graph.create_agent_tools(llm=DummyLLM())

    assert tools["validate_markdown"].__tool__.permission == "model_call"
    assert "llm_optional" in tools["validate_markdown"].__tool__.tags

def test_validate_markdown_consumes_llm_budget_when_fact_check_enabled(monkeypatch):
    class DummyLLM:
        def think(self, _messages, temperature=0):
            _ = temperature
            return '{"issues":[]}'

    monkeypatch.setenv("STORY_AGENT_ENABLE_FACT_CHECK_LLM", "1")
    tools = story_agent_graph.create_agent_tools(llm=DummyLLM())
    state = story_agent_state.create_initial_state("李白", llm_calls_limit=0)

    with pytest.raises(story_agent_tool_runner.ToolCallError, match="LLM_CALL_BUDGET_EXCEEDED"):
        story_agent_tool_runner.call_tool(
            state,
            tools["validate_markdown"],
            "# 李白\n",
            agent_step="critic_agent",
        )

def test_story_markdown_agent_does_not_consume_llm_budget_for_deterministic_overrides():
    agent = story_agent_graph.create_story_markdown_agent(
        llm=None,
        search_person_info_fn=lambda person_name: {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [],
            "places": [],
            "cautions": [],
        },
        fetch_ancient_place_map_fn=lambda place_name, **kwargs: {
            "query": place_name,
            "ancient_name": place_name,
            "modern_name": place_name,
            "lat": None,
            "lng": None,
            "source": "",
        },
        generate_markdown_fn=lambda structure: f"# {structure.get('person')}\n",
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=0,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert result["markdown"] == "# 李白\n"
    assert result["state"]["llm_calls_used"] == 0
    assert not any("LLM_CALL_BUDGET_EXCEEDED" in item for item in result["state"]["degraded_reasons"])

def test_default_search_person_info_collects_short_review_candidate_from_llm():
    class DummyLLM:
        def think(self, _messages, temperature=0):
            _ = temperature
            return (
                '{"dynasty":"唐朝","summary":"李白，唐代诗人。",'
                '"short_review_candidate":"天才诗人，浪漫主义高峰。",'
                '"identities":["诗人"],"achievements":["诗歌创作"],'
                '"timeline":[],"places":[],"cautions":[]}'
            )

    result = story_agent_graph.default_search_person_info("李白", llm=DummyLLM())

    assert result["summary"] == "李白，唐代诗人。"
    assert result["short_review_candidate"] == "天才诗人，浪漫主义高峰。"

def test_default_agent_llm_calls_bound_runtime_requests():
    class DummyLLM:
        def __init__(self):
            self.calls = []

        def think(self, messages, temperature=0, timeout=None, max_retries=None):
            self.calls.append(
                {
                    "messages": messages,
                    "temperature": temperature,
                    "timeout": timeout,
                    "max_retries": max_retries,
                }
            )
            if len(self.calls) == 1:
                return (
                    '{"dynasty":"唐朝","summary":"李白，唐代诗人。",'
                    '"short_review_candidate":"天才诗人，浪漫主义高峰。",'
                    '"identities":["诗人"],"achievements":["诗歌创作"],'
                    '"timeline":[],"places":[],"cautions":[]}'
                )
            return "# 李白\n"

    llm = DummyLLM()
    search_result = story_agent_graph.default_search_person_info("李白", llm=llm)
    markdown = story_agent_graph.default_generate_markdown(
        {
            "person": "李白",
            "plan": [],
            "search_result": search_result,
            "place_maps": [],
            "critic_feedback": [],
            "previous_draft": "",
        },
        llm=llm,
    )

    assert markdown == "# 李白\n"
    assert llm.calls[0]["timeout"] == 60
    assert llm.calls[0]["max_retries"] == 3
    assert llm.calls[1]["timeout"] == 120
    assert llm.calls[1]["max_retries"] == 3

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

    def _map(place_name: str, **kwargs):
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
    # P1/P2a: 修订轮 search_agent 复用缓存跳过 + P0: map_agent 跳过已编码地名
    # → 修订轮仅 editor + critic 产生工具调用
    assert len(result["state"]["tool_traces"]) == 6
    assert all("tool_name" in item for item in result["state"]["tool_traces"])
    assert [item.get("agent_step") for item in result["state"]["tool_traces"]] == [
        "search_agent",
        "map_agent",
        "editor_agent",
        "critic_agent",
        "editor_agent",
        "critic_agent",
    ]
    assert editor_structures[0]["runtime_reflection"]["tool_summary"]["total_calls"] >= 1
    assert "运行时反思" in editor_structures[0]["runtime_reflection_prompt"]
    assert editor_structures[1]["runtime_reflection"]["retry_summary"]["revision_count"] == 1
    # P1 拆分后 2 个地名分别编码，顺序非确定性（并行）
    assert len(calls) == 6
    assert calls[0] == "search:李白"
    assert calls.count("edit") == 2
    assert calls.count("critic") == 2
    assert "map:碎叶城" in calls

def test_story_markdown_agent_injects_short_review_candidate_into_history_reviews():
    def _search(person_name: str):
        return {
            "person": person_name,
            "summary": "李白，唐代诗人。",
            "short_review_candidate": "人物短评：短评：天才诗人，浪漫主义高峰。",
            "identities": ["诗人"],
            "achievements": ["诗歌创作"],
            "timeline": [],
            "places": [],
            "cautions": [],
        }

    def _generate(_structure):
        return (
            "# 人物 生平传记与足迹\n\n"
            "## 一、人物档案\n\n"
            "### 基本信息\n"
            "- **姓名**：李白\n"
            "- **时代**：唐朝\n"
            "- **出生**：701年，碎叶城（今吉尔吉斯斯坦托克马克）\n"
            "- **去世**：762年，当涂（今安徽马鞍山当涂县）\n"
            "- **享年**：61岁\n"
            "- **主要身份**：诗人\n"
            "- **历史地位**：浪漫主义诗歌代表\n"
            "- **主要成就**：诗歌创作\n\n"
            "### 生平概述\n李白，唐代诗人。\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 701年 | 碎叶城 | 吉尔吉斯斯坦托克马克 | 出生 |\n"
            "| 762年 | 当涂 | 安徽马鞍山当涂县 | 去世 |\n\n"
            "## 五、历史影响\n\n"
            "### 对当时的影响\n唐代诗坛影响深远。\n\n"
            "### 对后世的影响\n- 影响后世诗歌创作。\n\n"
            "### 历史评价\n- 诗风雄奇飘逸。\n"
        )

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=_generate,
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=2,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert "### 历史评价" in result["markdown"]
    assert "- 短评：天才诗人，浪漫主义高峰。" in result["markdown"]
    assert "- 短评：人物短评：短评：天才诗人，浪漫主义高峰。" not in result["markdown"]
    assert result["markdown"].count("短评：天才诗人，浪漫主义高峰。") == 1

def test_extract_places_for_mapping_ignores_instructional_critic_correction_text():
    state = {
        "search_result": {
            "places": [],
            "timeline": [],
        },
        "critic_feedback": [
            {
                "field": "location",
                "claim": "碎叶城",
                "correction": "补充出生地对应的现代地名",
                "confidence": 0.82,
                "reason": "出生地缺少现代城市名",
            }
        ],
    }

    assert story_agent_graph._extract_places_for_mapping(state) == ["碎叶城"]

def test_story_markdown_agent_preserves_failed_map_tool_trace():
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

    def _map(_place_name: str, **kwargs):
        raise RuntimeError("map boom")

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        fetch_ancient_place_map_fn=_map,
        generate_markdown_fn=lambda structure: f"# {structure.get('person')}\n",
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=4,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert result["markdown"] == "# 李白\n"
    assert any("map_agent:碎叶城:map boom" in item for item in result["state"]["degraded_reasons"])
    assert any(
        item.get("tool_name") == "fetch_ancient_place_map"
        and item.get("agent_step") == "map_agent"
        and item.get("success") is False
        for item in result["state"]["tool_traces"]
    )

def test_default_validate_markdown_flags_vague_modern_location():
    content = (
        "# 郦道元\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：郦道元\n"
        "- **时代**：北魏\n"
        "- **出生**：466年，范阳涿州（今河北涿州）\n"
        "- **去世**：527年，阴盘驿（今陕西临潼）\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 466年 | 范阳涿州 | 河北涿州 | 出生 |\n"
        "| 495年 | 北魏境内 | 北魏境内 | 任职 |\n"
        "| 527年 | 阴盘驿 | 陕西临潼 | 去世 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="郦道元")

    assert result["pass"] is False
    assert any("泛区域表述" in str(item.get("reason") or "") for item in result["issues"])

def test_default_validate_markdown_flags_misattributed_truth_quote_for_aristotle():
    content = (
        "# 亚里士多德\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：亚里士多德\n"
        "- **时代**：古希腊\n"
        "- **出生**：前384年，斯塔吉拉\n"
        "- **去世**：前322年，优卑亚岛\n\n"
        "## 三、人生历程与重要地点（按时间顺序）\n\n"
        "### 📍 重要地点：雅典\n"
        "- **名篇名句**：《形而上学》：“吾爱吾师，吾更爱真理。”\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 前384年 | 斯塔吉拉 | 希腊斯塔夫罗斯附近 | 出生 |\n"
        "| 前322年 | 优卑亚岛 | 希腊优卑亚岛 | 去世 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="亚里士多德")

    assert result["pass"] is False
    assert any("《形而上学》" in str(item.get("claim") or "") for item in result["issues"])
    assert any("逐字引文" in str(item.get("reason") or "") for item in result["issues"])

def test_default_validate_markdown_flags_work_description_misused_as_quote():
    content = (
        "# 闻立鹏\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：闻立鹏\n"
        "- **时代**：现代\n"
        "- **出生**：1931年，北京\n"
        "- **去世**：2022年，北京\n\n"
        "## 三、人生历程与重要地点（按时间顺序）\n\n"
        "### 📍 重要地点：北京\n"
        "- **名篇名句**：《红烛颂》：以闻一多形象象征燃烧的理想；《大火》：以象征手法表现历史激情。\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 1931年 | 北京 | 北京 | 出生 |\n"
        "| 2022年 | 北京 | 北京 | 去世 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="闻立鹏")

    assert result["pass"] is False
    assert any("作品说明" in str(item.get("reason") or "") for item in result["issues"])
    assert any("代表作品" in str(item.get("correction") or "") for item in result["issues"])

def test_default_validate_markdown_flags_broad_ancient_region_overmapped_to_single_city():
    content = (
        "# 霍去病\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：霍去病\n"
        "- **时代**：西汉\n"
        "- **出生**：约前140年，平阳\n"
        "- **去世**：前117年，长安\n"
        "- **享年**：约23岁\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 前121年 | 河西走廊 | 甘肃省张掖市 | 大破匈奴 |\n"
        "| 前117年 | 长安 | 陕西西安 | 去世 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="霍去病")

    assert result["pass"] is False
    assert any("过度一对一映射" in str(item.get("reason") or "") for item in result["issues"])

def test_default_validate_markdown_flags_exact_lifespan_when_years_are_approximate():
    content = (
        "# 霍去病\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：霍去病\n"
        "- **时代**：西汉\n"
        "- **出生**：约前140年，平阳\n"
        "- **去世**：前117年，长安\n"
        "- **享年**：23岁\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 前140年 | 平阳 | 山西临汾一带 | 出生 |\n"
        "| 前117年 | 长安 | 陕西西安 | 去世 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="霍去病")

    assert result["pass"] is False
    assert any("不确定性" in str(item.get("reason") or "") for item in result["issues"])

def test_default_validate_markdown_flags_chinese_numeral_lifespan_when_years_are_approximate():
    content = (
        "# 霍去病\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：霍去病\n"
        "- **时代**：西汉\n"
        "- **出生**：约前140年，平阳\n"
        "- **去世**：前117年，长安\n"
        "- **享年**：终年二十三岁\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 前140年 | 平阳 | 山西临汾一带 | 出生 |\n"
        "| 前117年 | 长安 | 陕西西安 | 去世 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="霍去病")

    assert result["pass"] is False
    assert any("完全确定的绝对结论" in str(item.get("reason") or "") for item in result["issues"])

def test_default_validate_markdown_flags_absolute_original_name_claim_for_zheng_he():
    content = (
        "# 郑和\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：郑和（原名马三保）\n"
        "- **时代**：明朝\n"
        "- **出生**：1371年，云南昆阳\n"
        "- **去世**：1433年，古里返航途中\n"
        "- **主要身份**：航海家\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 1371年 | 昆阳 | 云南昆明晋宁区 | 出生 |\n"
        "| 1433年 | 古里 | 印度喀拉拉邦卡利卡特 | 病逝 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="郑和")

    assert result["pass"] is False
    assert any("原名马三保" in str(item.get("claim") or "") for item in result["issues"])

def test_default_validate_markdown_flags_mixed_identity_tokens_in_name_line():
    content = (
        "# 陶渊明\n\n"
        "## 一、人物档案\n\n"
        "### 基本信息\n"
        "- **姓名**：陶渊明，又名潜，字元亮，号五柳先生\n"
        "- **时代**：东晋\n"
        "- **出生**：365年，浔阳柴桑\n"
        "- **去世**：427年，浔阳柴桑\n"
        "- **享年**：约62岁\n\n"
        "## 四、生平时间线\n\n"
        "| 年份 | 古称 | 现称 | 事件 |\n"
        "| --- | --- | --- | --- |\n"
        "| 365年 | 柴桑 | 江西九江柴桑区 | 出生 |\n"
        "| 427年 | 柴桑 | 江西九江柴桑区 | 去世 |\n"
    )

    result = story_agent_graph.default_validate_markdown(content, person="陶渊明")

    assert result["pass"] is False
    assert any("混写在同一结论里" in str(item.get("reason") or "") for item in result["issues"])

def test_story_markdown_agent_builtin_validator_revises_after_knowledge_claim_feedback():
    calls = []

    def _search(person_name: str):
        return {
            "person": person_name,
            "summary": "亚里士多德，古希腊哲学家。",
            "identities": ["哲学家"],
            "achievements": ["建立系统哲学体系"],
            "timeline": [{"year": "前384年", "event": "出生", "place": "斯塔吉拉"}],
            "places": [{"name": "雅典", "context": "讲学"}],
            "cautions": [],
        }

    def _generate(structure):
        calls.append("edit")
        if structure.get("critic_feedback"):
            return (
                "# 亚里士多德\n\n"
                "## 一、人物档案\n\n"
                "### 基本信息\n"
                "- **姓名**：亚里士多德\n"
                "- **时代**：古希腊\n"
                "- **出生**：前384年，斯塔吉拉（今希腊哈尔基季基半岛斯塔吉拉遗址）\n"
                "- **去世**：前322年，优卑亚岛（今希腊优卑亚岛）\n\n"
                "## 三、人生历程与重要地点（按时间顺序）\n\n"
                "### 📍 重要地点：雅典\n"
                "- **事件**：在雅典讲学并系统发展其哲学思想。\n"
                "- **相关思想**：后世常以“吾爱吾师，吾更爱真理”概括其重真理、重论证的学术立场，但不宜直接当作《形而上学》的逐字原文。\n\n"
                "## 四、生平时间线\n\n"
                "| 年份 | 古称 | 现称 | 事件 |\n"
                "| --- | --- | --- | --- |\n"
                "| 前384年 | 斯塔吉拉 | 希腊哈尔基季基半岛斯塔吉拉遗址 | 出生 |\n"
                "| 前322年 | 优卑亚岛 | 希腊优卑亚岛 | 去世 |\n"
                "\n## 五、地点坐标\n\n"
                "| 地点 | 纬度 | 经度 |\n"
                "| --- | --- | --- |\n"
                "| 希腊哈尔基季基半岛斯塔吉拉遗址 | 40.5900 | 23.8000 |\n"
                "| 希腊优卑亚岛 | 38.5236 | 23.8585 |\n"
            )
        return (
            "# 亚里士多德\n\n"
            "## 一、人物档案\n\n"
            "### 基本信息\n"
            "- **姓名**：亚里士多德\n"
            "- **时代**：古希腊\n"
            "- **出生**：前384年，斯塔吉拉（今希腊哈尔基季基半岛斯塔吉拉遗址）\n"
            "- **去世**：前322年，优卑亚岛（今希腊优卑亚岛）\n\n"
            "## 三、人生历程与重要地点（按时间顺序）\n\n"
            "### 📍 重要地点：雅典\n"
            "- **事件**：在雅典讲学并系统发展其哲学思想。\n"
            "- **名篇名句**：《形而上学》：“吾爱吾师，吾更爱真理。”\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 前384年 | 斯塔吉拉 | 希腊哈尔基季基半岛斯塔吉拉遗址 | 出生 |\n"
            "| 前322年 | 优卑亚岛 | 希腊优卑亚岛 | 去世 |\n"
            "\n## 五、地点坐标\n\n"
            "| 地点 | 纬度 | 经度 |\n"
            "| --- | --- | --- |\n"
            "| 希腊哈尔基季基半岛斯塔吉拉遗址 | 40.5900 | 23.8000 |\n"
            "| 希腊优卑亚岛 | 38.5236 | 23.8585 |\n"
        )

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=_generate,
        validate_markdown_fn=lambda content: story_agent_graph.default_validate_markdown(content, person="亚里士多德"),
        max_llm_calls=4,
    )

    result = agent["run"]("亚里士多德", 1, agent["max_llm_calls"])

    assert result["state"]["revision_count"] == 1
    assert "相关思想" in result["markdown"]
    assert "名篇名句" not in result["markdown"]
    assert not any("逐字引文" in str(item.get("reason") or "") for item in result["state"]["validation"]["issues"])
    assert calls == ["edit", "edit"]

def test_story_markdown_agent_revises_when_search_cautions_require_uncertainty_language():
    calls = []

    def _search(person_name: str):
        return {
            "person": person_name,
            "summary": "霍去病，西汉名将。",
            "short_review_candidate": "",
            "identities": ["将领"],
            "achievements": ["北击匈奴"],
            "timeline": [{"year": "前140年", "event": "出生", "place": "平阳"}],
            "places": [{"name": "平阳", "context": "出生地"}],
            "cautions": ["出生年份说法不一"],
        }

    def _generate(structure):
        calls.append("edit")
        if structure.get("critic_feedback"):
            return (
                "# 霍去病\n\n"
                "## 一、人物档案\n\n"
                "### 基本信息\n"
                "- **姓名**：霍去病\n"
                "- **时代**：西汉\n"
                "- **出生**：约前140年，平阳（今山西临汾一带，具体说法不一）\n"
                "- **去世**：前117年，长安（今陕西西安）\n"
                "- **享年**：约23岁\n"
                "- **主要身份**：将领\n"
                "- **历史地位**：西汉名将\n"
                "- **主要成就**：北击匈奴\n\n"
                "## 四、生平时间线\n\n"
                "| 年份 | 古称 | 现称 | 事件 |\n"
                "| --- | --- | --- | --- |\n"
                "| 前140年 | 平阳 | 山西临汾一带 | 出生 |\n"
                "| 前117年 | 长安 | 陕西西安 | 去世 |\n"
            )
        return (
            "# 霍去病\n\n"
            "## 一、人物档案\n\n"
            "### 基本信息\n"
            "- **姓名**：霍去病\n"
            "- **时代**：西汉\n"
            "- **出生**：前140年，平阳（今山西临汾一带）\n"
            "- **去世**：前117年，长安（今陕西西安）\n"
            "- **享年**：23岁\n"
            "- **主要身份**：将领\n"
            "- **历史地位**：西汉名将\n"
            "- **主要成就**：北击匈奴\n\n"
            "## 四、生平时间线\n\n"
            "| 年份 | 古称 | 现称 | 事件 |\n"
            "| --- | --- | --- | --- |\n"
            "| 前140年 | 平阳 | 山西临汾一带 | 出生 |\n"
            "| 前117年 | 长安 | 陕西西安 | 去世 |\n"
        )

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=_search,
        generate_markdown_fn=_generate,
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=4,
    )

    result = agent["run"]("霍去病", 1, agent["max_llm_calls"])

    assert calls == ["edit", "edit"]
    assert "说法不一" in result["markdown"] or "约前140年" in result["markdown"]
    assert result["state"]["revision_count"] == 1
    assert not any("search_result 已标注存疑点" in str(item.get("reason") or "") for item in result["state"]["validation"]["issues"])

def test_story_markdown_agent_blocks_non_authentic_person_before_generation(monkeypatch):
    monkeypatch.setattr(
        story_agent_graph,
        "classify_story_person_authenticity",
        lambda person, **_kwargs: (False, "mythological_character"),
    )

    agent = story_agent_graph.create_story_markdown_agent(
        search_person_info_fn=lambda person_name: (_ for _ in ()).throw(RuntimeError(f"should not search {person_name}")),
        generate_markdown_fn=lambda structure: (_ for _ in ()).throw(RuntimeError(f"should not edit {structure}")),
    )

    result = agent["run"]("嫦娥", 1, agent["max_llm_calls"])

    assert result["markdown"] == ""
    assert result["state"]["execution_trace"] == ["finish_agent"]
    assert result["state"]["validation"]["pass"] is False
    assert any("authenticity_filter:mythological_character" == item for item in result["state"]["degraded_reasons"])
    assert result["state"]["critic_feedback"][0]["field"] == "authenticity"

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

def test_generate_historical_markdown_blocks_non_authentic_person_before_agent_and_legacy(monkeypatch):
    class DummyLLM:
        def __init__(self):
            self.last_agent_runtime = {}
            self.events = []

        def think(self, _messages, temperature=0):
            raise AssertionError(f"should not call llm: {temperature}")

        def _emit(self, message):
            self.events.append(message)

    monkeypatch.setattr(
        story_agents,
        "classify_story_person_authenticity",
        lambda person, **_kwargs: (False, "mythological_character"),
    )
    monkeypatch.setattr(
        story_agents.story_agent_graph_utils,
        "generate_markdown_with_agents",
        lambda _llm, _person: (_ for _ in ()).throw(AssertionError("should not run agent")),
    )

    client = DummyLLM()
    result = story_agents.generate_historical_markdown(client, "嫦娥")

    assert result is None
    assert any("人物真实性过滤拦截" in item for item in client.events)
    assert client.last_agent_runtime["fallback"] == "authenticity_filter"
    assert client.last_agent_runtime["error"].startswith("人物真实性过滤拦截")

def test_generate_historical_markdown_allows_unknown_person_for_live_generation():
    class DummyLLM:
        def __init__(self):
            self.last_agent_runtime = {}
            self.events = []

        def think(self, _messages, temperature=0):
            raise AssertionError(f"should not call llm fallback: {temperature}")

        def _emit(self, message):
            self.events.append(message)

    original = story_agents.story_agent_graph_utils.generate_markdown_with_agents
    story_agents.story_agent_graph_utils.generate_markdown_with_agents = lambda _llm, person: {
        "markdown": f"# {person}\n",
        "state": {"execution_trace": ["supervisor", "finish_agent"]},
    }
    client = DummyLLM()
    try:
        result = story_agents.generate_historical_markdown(client, "海绵宝宝")
    finally:
        story_agents.story_agent_graph_utils.generate_markdown_with_agents = original

    assert result == "# 海绵宝宝"
    assert not any("人物真实性过滤拦截" in item for item in client.events)

def test_story_markdown_agent_uses_fallback_markdown_when_llm_budget_exhausted():
    calls = []

    class DummyLLM:
        def think(self, _messages, temperature=0):
            raise AssertionError(f"should not call llm: {temperature}")

    def _search(person_name: str, **kwargs):
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

    agent = story_agent_graph.create_story_markdown_agent(
        llm=DummyLLM(),
        search_person_info_fn=_search,
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=0,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert "## 李白" in result["markdown"]
    assert "### 生平" in result["markdown"]
    assert "**701年**" in result["markdown"]
    assert "碎叶城" in result["markdown"]
    assert calls == ["search:李白"]
    assert result["state"]["llm_calls_used"] == 0
    assert any("LLM_CALL_BUDGET_EXCEEDED" in item for item in result["state"]["degraded_reasons"])

def test_story_markdown_agent_falls_back_when_editor_raises():
    def _search(person_name: str, **kwargs):
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
        fetch_ancient_place_map_fn=lambda place_name, **kwargs: {
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
    assert "### 生平" in result["markdown"]
    assert "碎叶城" in result["markdown"]
    assert any("editor_agent:editor boom" in item for item in result["state"]["degraded_reasons"])

def test_story_markdown_agent_counts_failed_search_call_against_budget():
    calls = []

    class DummyLLM:
        def think(self, _messages, temperature=0):
            raise AssertionError(f"should not call llm: {temperature}")

    def _search(_person_name: str, **kwargs):
        calls.append("search")
        raise RuntimeError("search boom")
    _search.__story_agent_uses_llm__ = True

    agent = story_agent_graph.create_story_markdown_agent(
        llm=DummyLLM(),
        search_person_info_fn=_search,
        validate_markdown_fn=lambda content: {"pass": True, "risk_level": "low", "issues": [], "notes": content},
        max_llm_calls=1,
    )

    result = agent["run"]("李白", 0, agent["max_llm_calls"])

    assert calls == ["search", "search", "search"]
    assert result["state"]["llm_calls_used"] == 1
    assert any("search_agent:search boom" in item for item in result["state"]["degraded_reasons"])
    assert any("editor_agent:LLM_CALL_BUDGET_EXCEEDED:1/1" in item for item in result["state"]["degraded_reasons"])
    assert "降级流程生成" in result["markdown"]

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

    def _map(place_name: str, **kwargs):
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

    assert len(calls) == 6
    assert calls.count("search") == 1
    assert calls.count("map") == 1
    assert calls.count("edit") == 2
    assert calls.count("critic") == 2
    assert result["state"]["revision_count"] == 1
    assert result["state"]["needs_revision"] is False
    assert result["state"]["execution_trace"].count("critic_agent") == 2
    assert result["markdown"]

def test_manual_story_markdown_agent_finishes_when_max_revisions_is_high(monkeypatch):
    original_langgraph_available = story_agent_graph._LANGGRAPH_AVAILABLE
    original_state_graph = story_agent_graph.StateGraph
    monkeypatch.setattr(story_agent_graph, "_LANGGRAPH_AVAILABLE", False)
    monkeypatch.setattr(story_agent_graph, "StateGraph", None)
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

    def _map(place_name: str, **kwargs):
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

    validation_calls = {"count": 0}

    def _validate(_content: str):
        validation_calls["count"] += 1
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

    try:
        agent = story_agent_graph.create_story_markdown_agent(
            search_person_info_fn=_search,
            fetch_ancient_place_map_fn=_map,
            generate_markdown_fn=_generate,
            validate_markdown_fn=_validate,
            max_llm_calls=20,
        )
        result = agent["run"]("李白", 5, agent["max_llm_calls"])
    finally:
        monkeypatch.setattr(story_agent_graph, "_LANGGRAPH_AVAILABLE", original_langgraph_available)
        monkeypatch.setattr(story_agent_graph, "StateGraph", original_state_graph)

    assert validation_calls["count"] == 6
    assert result["markdown"]
    assert result["state"]["execution_trace"][-1] == "finish_agent"
    assert result["state"]["revision_count"] == 5
    assert result["state"]["needs_revision"] is False
    assert "manual_runner:max_iterations_exceeded" not in " ".join(result["state"].get("degraded_reasons") or [])
    assert calls.count("critic") == 6

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
    place_names = [f"地点{i:02d}" for i in range(12)]

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

    def _map(place_name: str, **kwargs):
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
    assert sorted(mapped) == sorted(place_names)
    assert len(result["state"]["place_maps"]) == 12

def test_story_markdown_agent_maps_timeline_places_even_when_places_list_is_empty():
    mapped = []

    def _search(person_name: str):
        return {
            "person": person_name,
            "summary": "测试人物",
            "identities": ["人物"],
            "achievements": ["测试"],
            "timeline": [
                {"year": "701年", "event": "出生", "place": "碎叶城"},
                {"year": "762年", "event": "去世", "place": "当涂"},
            ],
            "places": [],
            "cautions": [],
        }

    def _map(place_name: str, **kwargs):
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
    assert sorted(mapped) == ["当涂", "碎叶城"]
    assert sorted([item["query"] for item in result["state"]["place_maps"]]) == ["当涂", "碎叶城"]

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

    def _map(place_name: str, **kwargs):
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

def test_extract_year_handles_bce_dates():
    """公元前年份应当返回负数，否则会污染寿命/时间线一致性校验。"""

    assert story_agent_graph._extract_year("公元前551年") == -551
    assert story_agent_graph._extract_year("前479年") == -479
    assert story_agent_graph._extract_year("公元220年") == 220
    assert story_agent_graph._extract_year("220年") == 220
    assert story_agent_graph._extract_year("没有年份") is None

def test_lifespan_issues_does_not_misfire_for_bce_person():
    """孔子（前551–前479，享年73）应当能被一致性校验正确放行。"""

    class _Basic:
        birth_text = "公元前551年，鲁国陬邑"
        death_text = "公元前479年，鲁国"
        lifespan = "73岁"
        name = "孔子"

    class _Doc:
        basic_info = _Basic()

    issues = story_agent_graph._lifespan_issues(_Doc())
    # 修复前 birth_year=551, death_year=479 → estimated=-72 → 与 73 差 145，会误报
    # 修复后 birth_year=-551, death_year=-479 → estimated=72 → 与 73 仅差 1，应通过
    assert all(item.get("field") != "age" or "不自洽" not in str(item.get("reason") or "") for item in issues)
