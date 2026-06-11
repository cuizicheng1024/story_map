import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import map_client


def test_geocode_city_falls_back_to_public_geocoder_without_qveris(monkeypatch):
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)

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


def test_geocode_city_falls_back_to_wikidata_for_foreign_place(monkeypatch):
    monkeypatch.setattr(map_client, "_geocode_cache_get", lambda _name: None)
    monkeypatch.setattr(map_client, "_geocode_cache_set", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(map_client, "_amap_webservice_geocode", lambda _name: None)
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
