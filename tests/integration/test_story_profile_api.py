import sys
from types import SimpleNamespace

from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storymap.script.api import profile_api as story_profile_api
from storymap.script.core import parsers
from storymap.script.profile import builder as profile_builder


def test_create_profile_api_from_geocode_api_queues_unresolved_profile_location():
    queued = []

    def _submit(payload):
        queued.append(dict(payload))
        place_name = str(payload.get("place_name") or "")
        return {
            "status": "queued",
            "queued": True,
            "raw_place": place_name,
            "normalized_place_key": place_name,
            "recommended_search_name": place_name,
            "review_item_id": place_name,
            "queue_path": "/tmp/hard_place_review_queue.json",
            "reason": str(payload.get("reason") or ""),
        }

    api = story_profile_api.create_profile_api_from_geocode_api(
        parser_utils=parsers,
        profile_builder_utils=profile_builder,
        generation_service_utils=SimpleNamespace(render_html=lambda *args, **kwargs: ""),
        geocode_city=lambda _name: None,
        geocode_api={
            "lookup_coords_from_historical_index": lambda *_names: None,
            "resolve_place_coord": lambda *_args, **_kwargs: None,
            "split_ancient_modern": lambda text, event_callback=None: ("汴京", "河南开封") if "汴京" in str(text or "") else ("", str(text or "")),
            "batch_split_ancient_modern": lambda _texts, event_callback=None: {},
            "fuzzy_coord_lookup": lambda _coords_cache, _candidates: None,
            "submit_hard_place_review": _submit,
        },
        render_profile_html=lambda _profile: "",
        build_info_panel_html=lambda *_args, **_kwargs: "",
        render_amap_html=lambda *_args, **_kwargs: "",
    )

    md = """# 苏轼

## 一、人物档案

### 基本信息
- **姓名**：苏轼
- **时代**：北宋

## 三、人生历程与重要地点（按时间顺序）

### 📍 重要地点：开封
- **公元纪年**：1057年
- **位置**：汴京（今河南开封）
- **事迹**：赴京应试。
"""

    profile = api["load_profile_from_md"](md, fallback_person="苏轼", allow_geocode=True)

    assert profile is not None
    assert profile["locations"] == []
    assert len(queued) == 1
    assert queued[0]["place_name"] == "河南开封"
    assert queued[0]["person"] == "苏轼"
    assert queued[0]["reason"] == "profile_resolve_place_coord_failed"
    assert "build_profile_data" in str(queued[0]["context"] or "")


def test_create_profile_api_build_points_queues_geocode_miss():
    queued = []

    def _submit(payload):
        queued.append(dict(payload))
        place_name = str(payload.get("place_name") or "")
        return {
            "status": "queued",
            "queued": True,
            "raw_place": place_name,
            "normalized_place_key": place_name,
            "recommended_search_name": place_name,
            "review_item_id": place_name,
            "queue_path": "/tmp/hard_place_review_queue.json",
            "reason": str(payload.get("reason") or ""),
        }

    api = story_profile_api.create_profile_api(
        parser_utils=parsers,
        profile_builder_utils=profile_builder,
        generation_service_utils=SimpleNamespace(render_html=lambda *args, **kwargs: ""),
        geocode_city=lambda _name: None,
        lookup_coords_from_historical_index=lambda *_names: None,
        resolve_place_coord=lambda *_args, **_kwargs: None,
        split_ancient_modern=lambda text, event_callback=None: ("", str(text or "")),
        batch_split_ancient_modern=lambda _texts, event_callback=None: {},
        fuzzy_coord_lookup=lambda _coords_cache, _candidates: None,
        submit_hard_place_review=_submit,
        render_profile_html=lambda _profile: "",
        build_info_panel_html=lambda *_args, **_kwargs: "",
        render_amap_html=lambda *_args, **_kwargs: "",
    )

    points = api["build_points"](
        [{"ancient": "汴京", "modern": "河南开封"}],
        [],
        allow_geocode=True,
        fallback_person="苏轼",
    )

    assert points == []
    assert len(queued) == 1
    assert queued[0]["place_name"] == "河南开封"
    assert queued[0]["person"] == "苏轼"
    assert queued[0]["reason"] == "profile_build_points_geocode_failed"
    assert queued[0]["context"] == "build_points"
