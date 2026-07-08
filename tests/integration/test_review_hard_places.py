import importlib
import json
import sys
from tests_support import REPO_ROOT

def test_collect_review_items_merges_negative_cache_and_low_coverage():
    module = importlib.import_module("tools.review_hard_places")
    low_coverage_report = {
        "top_people": [
            {
                "person": "唐东杰布",
                "file": "storymap/examples/story/唐东杰布.md",
                "birth_missing_coord": True,
                "birth_location": "后藏窝托加巴",
                "death_missing_coord": False,
                "death_location": "",
                "unresolved_locations": ["后藏窝托加巴", "拉萨"],
            }
        ]
    }
    negative_cache = {
        "后藏窝托加巴": {"reason": "no_result", "updated_at": 1.0, "expires_at": 2.0}
    }

    items = module.collect_review_items(low_coverage_report, negative_cache, limit=10)
    target = next(item for item in items if item["raw_place"] == "后藏窝托加巴")

    assert target["sources"]["negative_cache"] is True
    assert target["sources"]["low_coverage_mentions"] == 2
    assert target["negative_cache"]["reason"] == "no_result"
    assert any(ref["person"] == "唐东杰布" for ref in target["references"])

def test_collect_review_items_skips_placeholder_noise():
    module = importlib.import_module("tools.review_hard_places")
    low_coverage_report = {
        "top_people": [
            {
                "person": "示例人物",
                "file": "storymap/examples/story/示例人物.md",
                "birth_missing_coord": False,
                "birth_location": "",
                "death_missing_coord": False,
                "death_location": "",
                "unresolved_locations": ["—", "公元", "后藏窝托加巴"],
            }
        ]
    }

    items = module.collect_review_items(low_coverage_report, {}, limit=10)

    names = [item["raw_place"] for item in items]
    assert names == ["后藏窝托加巴"]

def test_enrich_items_with_llm_updates_review_fields():
    module = importlib.import_module("tools.review_hard_places")
    items = [
        {
            **module._build_heuristic_review("美国纽约州纽约市"),
            "sources": {"negative_cache": True, "low_coverage_mentions": 1},
            "negative_cache": {"reason": "no_result"},
            "references": [{"person": "奥本海默", "file": "story.md", "kind": "unresolved", "snippet": "在美国纽约州纽约市出生"}],
        }
    ]

    class FakeLLM:
        def think(self, _messages, temperature=0):
            _ = temperature
            return json.dumps(
                [
                    {
                        "raw_place": "美国纽约州纽约市",
                        "place_type": "modern_place",
                        "ancient_name": "",
                        "modern_candidates": ["纽约市", "New York City, United States"],
                        "recommended_search_name": "纽约市",
                        "country": "美国",
                        "admin_hint": "纽约州",
                        "is_point_like": True,
                        "confidence": 0.96,
                        "evidence": ["上下文明确指出是现代城市"],
                        "needs_human_review": True,
                        "should_write_to": "place_aliases",
                    }
                ],
                ensure_ascii=False,
            )

    enriched = module.enrich_items_with_llm(items, llm_mode="on", llm_factory=lambda: FakeLLM())

    assert enriched[0]["llm_status"] == "ok"
    assert enriched[0]["recommended_search_name"] == "纽约市"
    assert enriched[0]["country"] == "美国"
    assert enriched[0]["modern_candidates"] == ["纽约市", "New York City, United States"]

def test_main_writes_review_queue_files(tmp_path, monkeypatch):
    module = importlib.import_module("tools.review_hard_places")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "唐东杰布.md").write_text("# 唐东杰布\n\n- 出生于后藏窝托加巴\n", encoding="utf-8")
    low_coverage_path = tmp_path / "data" / "reports" / "low_coverage_story_report.json"
    negative_cache_path = tmp_path / ".cache" / "map_story_geocode_negative_cache.json"
    out_json = tmp_path / "data" / "runtime" / "hard_place_review_queue.json"
    out_md = tmp_path / "data" / "runtime" / "hard_place_review_queue.md"
    low_coverage_path.parent.mkdir(parents=True)
    negative_cache_path.parent.mkdir(parents=True)
    low_coverage_path.write_text(
        json.dumps(
            {
                "top_people": [
                    {
                        "person": "唐东杰布",
                        "file": "storymap/examples/story/唐东杰布.md",
                        "birth_missing_coord": False,
                        "birth_location": "",
                        "death_missing_coord": False,
                        "death_location": "",
                        "unresolved_locations": ["后藏窝托加巴"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    negative_cache_path.write_text(
        json.dumps({"后藏窝托加巴": {"reason": "no_result", "updated_at": 1, "expires_at": 2}}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_hard_places.py",
            "--low-coverage-json",
            str(low_coverage_path),
            "--negative-cache-json",
            str(negative_cache_path),
            "--story-dir",
            str(story_dir),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--llm-mode",
            "off",
        ],
    )

    rc = module.main()

    assert rc == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["summary"]["items"] == 1
    assert payload["items"][0]["raw_place"] == "后藏窝托加巴"
    assert "疑难地点人工审核队列" in out_md.read_text(encoding="utf-8")

def test_apply_confirmed_items_writes_place_aliases_and_historical_index(tmp_path):
    module = importlib.import_module("tools.review_hard_places")
    place_aliases_path = tmp_path / "data" / "corpus" / "place_aliases.json"
    historical_index_path = tmp_path / "data" / "corpus" / "historical_places_index.jsonl"
    queue = {
        "summary": {"items": 2, "with_negative_cache": 0, "with_low_coverage_context": 2, "llm_enriched": 2},
        "items": [
            {
                "raw_place": "美国纽约州纽约市",
                "recommended_search_name": "纽约市",
                "modern_candidates": ["纽约市", "New York City, United States"],
                "should_write_to": "place_aliases",
                "human_decision": "approve",
                "approved_lat": 40.7128,
                "approved_lon": -74.0060,
                "human_notes": "",
            },
            {
                "raw_place": "吴兴武康（今浙江省湖州市德清县一带）",
                "ancient_name": "吴兴武康",
                "recommended_search_name": "德清县",
                "modern_candidates": ["浙江省湖州市德清县"],
                "should_write_to": "historical_index",
                "human_decision": "approved",
                "approved_lat": 30.5429,
                "approved_lon": 119.9774,
                "human_notes": "",
            },
        ],
    }

    result = module.apply_confirmed_items(
        queue,
        place_aliases_path=place_aliases_path,
        historical_index_path=historical_index_path,
    )

    aliases_payload = json.loads(place_aliases_path.read_text(encoding="utf-8"))
    assert aliases_payload["美国纽约州纽约市"]["names"] == ["纽约市", "New York City, United States"]
    assert aliases_payload["美国纽约州纽约市"]["coords"] == [40.7128, -74.006]
    hist_rows = [json.loads(line) for line in historical_index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert hist_rows == [
        {
            "ancient_name": "吴兴武康",
            "modern_name": "德清县",
            "lat": 30.5429,
            "lon": 119.9774,
        }
    ]
    assert result["items"][0]["status"] == "applied"
    assert result["items"][1]["status"] == "applied"
    assert result["apply_summary"]["applied"] == 2

def test_main_apply_confirmed_updates_queue_and_outputs(tmp_path, monkeypatch):
    module = importlib.import_module("tools.review_hard_places")
    queue_path = tmp_path / "data" / "runtime" / "hard_place_review_queue.json"
    md_path = tmp_path / "data" / "runtime" / "hard_place_review_queue.md"
    place_aliases_path = tmp_path / "data" / "corpus" / "place_aliases.json"
    historical_index_path = tmp_path / "data" / "corpus" / "historical_places_index.jsonl"
    queue_path.parent.mkdir(parents=True)
    queue_path.write_text(
        json.dumps(
            {
                "summary": {"items": 1, "with_negative_cache": 0, "with_low_coverage_context": 1, "llm_enriched": 1},
                "items": [
                    {
                        "raw_place": "爱尔兰都柏林",
                        "recommended_search_name": "都柏林",
                        "modern_candidates": ["都柏林", "Dublin, Ireland"],
                        "should_write_to": "place_aliases",
                        "human_decision": "approve",
                        "approved_lat": 53.3498,
                        "approved_lon": -6.2603,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_hard_places.py",
            "--apply-confirmed",
            "--queue-json",
            str(queue_path),
            "--out-md",
            str(md_path),
            "--place-aliases-json",
            str(place_aliases_path),
            "--historical-index-jsonl",
            str(historical_index_path),
        ],
    )

    rc = module.main()

    assert rc == 0
    updated_queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert updated_queue["items"][0]["status"] == "applied"
    aliases_payload = json.loads(place_aliases_path.read_text(encoding="utf-8"))
    assert aliases_payload["爱尔兰都柏林"]["names"] == ["都柏林", "Dublin, Ireland"]
    assert "[apply] applied=1 skipped=0 failed=0" not in md_path.read_text(encoding="utf-8")
