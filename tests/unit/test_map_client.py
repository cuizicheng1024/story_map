import json
import os
import subprocess
import sys

from tests_support import REPO_ROOT

from storymap.script.map import map_client

def test_geocode_min_interval_invalid_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("MAP_STORY_GEOCODE_MIN_INTERVAL", "invalid")
    monkeypatch.setenv("MAP_STORY_AMAP_MIN_INTERVAL", "oops")

    assert map_client._geocode_rate_limit() is None
    assert map_client._amap_rate_limit() is None

def test_map_client_import_tolerates_invalid_http_concurrency_env():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from storymap.script.map import map_client; print(bool(map_client))",
        ],
        cwd=str(REPO_ROOT),
        env={
            **dict(os.environ),
            "MAP_STORY_GEOCODE_HTTP_CONCURRENCY": "oops",
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "True" in result.stdout

def test_geocode_city_falls_back_to_public_geocoder_without_qveris(monkeypatch):
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)
    monkeypatch.setattr(map_client, "_monid_geocode_enabled", lambda: False)

    calls = []

    def _fake_nominatim(name: str, force_cn: bool = False):
        calls.append((name, force_cn))
        return (39.9042, 116.4074)

    monkeypatch.setattr(map_client, "_geocode_nominatim", _fake_nominatim)

    result = map_client.geocode_city("北京")

    assert result == (39.9042, 116.4074)
    assert calls

def test_build_geocode_candidates_skips_placeholder_dash():
    assert map_client._build_geocode_candidates("—") == []

def test_build_geocode_candidates_extracts_foreign_city_core_name():
    candidates = map_client._build_geocode_candidates("爱尔兰都柏林")

    assert "爱尔兰都柏林" in candidates
    assert "都柏林" in candidates

def test_build_geocode_candidates_rejects_non_place_phrases():
    assert map_client._build_geocode_candidates("中国去世") == []
    assert map_client._build_geocode_candidates("地点不详（存疑）") == []

def test_build_geocode_candidates_trims_birth_context_into_place_names():
    candidates = map_client._build_geocode_candidates("出生于北京（今中国北京市）")

    assert "北京" in candidates
    assert "中国北京市" in candidates
    assert "出生于北京" not in candidates

def test_geocode_city_falls_back_to_wikidata_for_foreign_place(monkeypatch):
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)
    monkeypatch.setattr(map_client, "_monid_geocode_enabled", lambda: False)
    monkeypatch.setattr(
        map_client,
        "_geocode_nominatim",
        lambda _name, force_cn=False: (_ for _ in ()).throw(AssertionError("foreign lookup should try wikidata before nominatim")),
    )

    calls = []

    def _fake_wikidata(name: str):
        calls.append(name)
        if "都柏林" in name:
            return (53.3498, -6.2603)
        return None

    monkeypatch.setattr(map_client, "_geocode_wikidata", _fake_wikidata)

    result = map_client.geocode_city("爱尔兰都柏林")

    assert result == (53.3498, -6.2603)
    assert calls

def test_geocode_city_retries_without_cn_bias_for_foreign_city_written_in_chinese(monkeypatch):
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)
    monkeypatch.setattr(map_client, "_monid_geocode_enabled", lambda: False)
    monkeypatch.setattr(map_client, "_geocode_wikidata", lambda _name: None)

    calls = []

    def _fake_nominatim(name: str, force_cn: bool = False):
        calls.append((name, force_cn))
        if name == "都柏林" and force_cn is False:
            return (53.3498, -6.2603)
        return None

    monkeypatch.setattr(map_client, "_geocode_nominatim", _fake_nominatim)

    result = map_client.geocode_city("都柏林")

    assert result == (53.3498, -6.2603)
    assert ("都柏林", True) in calls
    assert ("都柏林", False) in calls

def test_geocode_city_negative_cache_short_circuits_repeated_failures(monkeypatch):
    map_client._reset_geocode_runtime_state()
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)
    monkeypatch.setattr(map_client, "_monid_geocode_enabled", lambda: False)
    monkeypatch.setattr(map_client, "_geocode_wikidata", lambda _name: None)
    calls = {"count": 0}

    def _fake_nominatim(_name: str, force_cn: bool = False):
        _ = force_cn
        calls["count"] += 1
        return None

    monkeypatch.setattr(map_client, "_geocode_nominatim", _fake_nominatim)

    assert map_client.geocode_city("测试失败地名") is None
    first_call_count = calls["count"]
    assert map_client.geocode_city("测试失败地名") is None
    snapshot = map_client.geocode_metrics_snapshot()

    assert first_call_count >= 1
    assert calls["count"] == first_call_count
    assert snapshot["negative_cache_hits"] == 1
    assert snapshot["failures"] == 1
    assert snapshot["negative_cache_size"] >= 1

def test_geocode_negative_cache_persists_to_disk_and_reloads(monkeypatch, tmp_path):
    negative_cache_path = tmp_path / "map_story_geocode_negative_cache.json"
    monkeypatch.setattr(map_client, "_GEOCODE_NEGATIVE_CACHE_PATH", str(negative_cache_path))
    monkeypatch.setattr(map_client, "_GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS", 0.0)
    monkeypatch.setattr(map_client, "_resolve_geocode_negative_cache_path", lambda: str(negative_cache_path))
    map_client._reset_geocode_runtime_state()

    map_client._geocode_negative_cache_set("测试失败地名", reason="no_result")

    persisted = json.loads(negative_cache_path.read_text(encoding="utf-8"))
    assert persisted["测试失败地名"]["reason"] == "no_result"
    assert float(persisted["测试失败地名"]["expires_at"]) > float(persisted["测试失败地名"]["updated_at"])

    map_client._reset_geocode_runtime_state()
    map_client._load_geocode_negative_cache()

    cached = map_client._geocode_negative_cache_get("测试失败地名")
    assert cached is not None
    assert cached["reason"] == "no_result"

def test_geocode_city_uses_persisted_negative_cache_after_runtime_reset(monkeypatch, tmp_path):
    negative_cache_path = tmp_path / "map_story_geocode_negative_cache.json"
    monkeypatch.setattr(map_client, "_GEOCODE_NEGATIVE_CACHE_PATH", str(negative_cache_path))
    monkeypatch.setattr(map_client, "_GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS", 0.0)
    monkeypatch.setattr(map_client, "_resolve_geocode_negative_cache_path", lambda: str(negative_cache_path))
    map_client._reset_geocode_runtime_state()
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)
    monkeypatch.setattr(map_client, "_monid_geocode_enabled", lambda: False)
    monkeypatch.setattr(map_client, "_geocode_wikidata", lambda _name: None)
    calls = {"count": 0}

    def _fake_nominatim(_name: str, force_cn: bool = False):
        _ = force_cn
        calls["count"] += 1
        return None

    monkeypatch.setattr(map_client, "_geocode_nominatim", _fake_nominatim)

    assert map_client.geocode_city("测试失败地名") is None
    first_call_count = calls["count"]
    assert first_call_count >= 1

    map_client._reset_geocode_runtime_state()
    map_client._load_geocode_negative_cache()

    assert map_client.geocode_city("测试失败地名") is None
    snapshot = map_client.geocode_metrics_snapshot()

    assert calls["count"] == first_call_count
    assert snapshot["negative_cache_hits"] == 1

def test_geocode_negative_cache_clear_updates_persisted_file(monkeypatch, tmp_path):
    negative_cache_path = tmp_path / "map_story_geocode_negative_cache.json"
    monkeypatch.setattr(map_client, "_GEOCODE_NEGATIVE_CACHE_PATH", str(negative_cache_path))
    monkeypatch.setattr(map_client, "_GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS", 0.0)
    monkeypatch.setattr(map_client, "_resolve_geocode_negative_cache_path", lambda: str(negative_cache_path))
    map_client._reset_geocode_runtime_state()

    map_client._geocode_negative_cache_set("测试失败地名", reason="no_result")
    monkeypatch.setattr(map_client, "_GEOCODE_NEGATIVE_CACHE_LAST_SAVE_TS", 0.0)
    map_client._geocode_negative_cache_clear("测试失败地名")

    persisted = json.loads(negative_cache_path.read_text(encoding="utf-8"))
    assert "测试失败地名" not in persisted

def test_fetch_json_uses_configured_timeout(monkeypatch):
    observed = []

    class _FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"{}"

    def _fake_urlopen(_req, timeout=0):
        observed.append(timeout)
        return _FakeResp()

    monkeypatch.setenv("MAP_STORY_GEOCODE_FETCH_TIMEOUT", "7")
    monkeypatch.setattr(map_client, "urlopen", _fake_urlopen)

    assert map_client._fetch_json("https://example.com") == {}
    assert observed == [7]

def test_geocode_city_uses_monid_before_public_geocoder(monkeypatch):
    map_client._reset_geocode_runtime_state()
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)
    monkeypatch.setattr(map_client, "_monid_geocode_enabled", lambda: True)
    monkeypatch.setattr(map_client, "_geocode_wikidata", lambda _name: None)
    calls = []

    def _fake_monid(name: str):
        calls.append(name)
        return (31.2304, 121.4737)

    monkeypatch.setattr(map_client, "_monid_geocode", _fake_monid)
    monkeypatch.setattr(
        map_client,
        "_geocode_nominatim",
        lambda _name, force_cn=False: (_ for _ in ()).throw(AssertionError("monid result should short-circuit nominatim")),
    )

    result = map_client.geocode_city("上海")

    assert result == (31.2304, 121.4737)
    assert calls

def test_monid_geocode_posts_expected_payload(monkeypatch):
    requests = []
    monkeypatch.setenv("MONID_API_KEY", "monid_live_test")

    def _fake_post_json(url: str, payload: object, *, headers=None, timeout=None):
        requests.append(
            {
                "url": url,
                "payload": payload,
                "headers": dict(headers or {}),
                "timeout": timeout,
            }
        )
        return {
            "status": "COMPLETED",
            "providerResponse": {"httpStatus": 200},
            "output": {"found": True, "latitude": 39.9027, "longitude": 116.3914},
        }

    monkeypatch.setattr(map_client, "_post_json", _fake_post_json)

    result = map_client._monid_geocode("北京市东城区天安门广场")

    assert result == (39.9027, 116.3914)
    assert requests == [
        {
            "url": "https://api.monid.ai/v1/run",
            "payload": {
                "provider": "api.strale.io",
                "endpoint": "/x402/address-geocode",
                "input": {"queryParams": {"address": "北京市东城区天安门广场"}},
            },
            "headers": {"Authorization": "Bearer monid_live_test"},
            "timeout": map_client._monid_timeout_seconds(),
        }
    ]
