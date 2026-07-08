import json
import time
from concurrent.futures import ThreadPoolExecutor

from storymap.script.map import geocode_api as story_geocode_api

class _FakeGeocodeService:
    @staticmethod
    def split_ancient_modern(loc_text: str, event_callback=None):
        _ = event_callback
        return str(loc_text or "").strip(), ""

    @staticmethod
    def normalize_place_key(text: str) -> str:
        return str(text or "").strip()

def test_submit_hard_place_for_review_skips_invalid_place_name(tmp_path, monkeypatch):
    queue_path = tmp_path / "data" / "runtime" / "hard_place_review_queue.json"
    monkeypatch.setenv("STORY_HARD_PLACE_QUEUE_JSON", str(queue_path))

    result = story_geocode_api.submit_hard_place_for_review(
        {
            "place_name": "不详",
            "person": "测试人物",
            "reason": "profile_build_points_geocode_failed",
        },
        geocode_service_utils=_FakeGeocodeService(),
    )

    assert result["status"] == "skipped"
    assert result["queued"] is False
    assert result["reason"] == "invalid_place_name"
    assert queue_path.exists() is False

def test_submit_hard_place_for_review_keeps_all_entries_under_concurrency(tmp_path, monkeypatch):
    queue_path = tmp_path / "data" / "runtime" / "hard_place_review_queue.json"
    monkeypatch.setenv("STORY_HARD_PLACE_QUEUE_JSON", str(queue_path))

    original_write = story_geocode_api._write_json_dict

    def slow_write(path, data):
        time.sleep(0.05)
        return original_write(path, data)

    monkeypatch.setattr(story_geocode_api, "_write_json_dict", slow_write)

    def submit(place_name: str) -> None:
        story_geocode_api.submit_hard_place_for_review(
            {
                "place_name": place_name,
                "person": "测试人物",
                "reason": "geocode_failed",
            },
            geocode_service_utils=_FakeGeocodeService(),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit, "碎叶城"), executor.submit(submit, "汴京")]
        for future in futures:
            future.result()

    payload = json.loads(queue_path.read_text(encoding="utf-8"))
    raw_places = {item["raw_place"] for item in payload["items"]}

    assert raw_places == {"碎叶城", "汴京"}
