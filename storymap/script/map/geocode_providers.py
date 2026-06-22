from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional, Sequence, Tuple


DEFAULT_ENDPOINTS: Sequence[Tuple[str, str]] = (
    ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q={}", "list"),
    ("https://geocode.maps.co/search?q={}", "list"),
    ("https://photon.komoot.io/api/?limit=1&q={}", "photon"),
)
WIKIDATA_SEARCH_ENDPOINT = (
    "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&type=item"
    "&limit=5&language={language}&uselang={language}&search={query}"
)
WIKIDATA_ENTITY_ENDPOINT = "https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"


def monid_geocode(
    name: str,
    *,
    api_key: str,
    post_json: Callable[..., Optional[object]],
    timeout_seconds: int,
    record_metric: Callable[[str], None],
    is_valid_coord: Callable[[object, object], bool],
) -> Optional[Tuple[float, float]]:
    query = str(name or "").strip()
    if not api_key or not query:
        return None
    record_metric("monid_requests")
    payload = post_json(
        "https://api.monid.ai/v1/run",
        {
            "provider": "api.strale.io",
            "endpoint": "/x402/address-geocode",
            "input": {"queryParams": {"address": query}},
        },
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=timeout_seconds,
    )
    if not isinstance(payload, dict):
        record_metric("monid_failures")
        return None
    provider_response = payload.get("providerResponse")
    if isinstance(provider_response, dict):
        try:
            http_status = int(provider_response.get("httpStatus") or 0)
        except Exception:
            http_status = 0
        if http_status >= 400:
            record_metric("monid_failures")
            return None
    status = str(payload.get("status") or "").strip().upper()
    if status and status != "COMPLETED":
        record_metric("monid_failures")
        return None
    output = payload.get("output")
    if not isinstance(output, dict):
        record_metric("monid_failures")
        return None
    if output.get("found") is False:
        record_metric("monid_failures")
        return None
    lat = output.get("latitude")
    lon = output.get("longitude")
    if not is_valid_coord(lat, lon):
        record_metric("monid_failures")
        return None
    record_metric("monid_successes")
    return float(lat), float(lon)


def geocode_wikidata(
    name: str,
    *,
    fetch_json: Callable[..., Optional[object]],
    quote_text: Callable[[str], str],
    record_metric: Callable[[str], None],
    is_valid_coord: Callable[[object, object], bool],
    is_meaningful_place_candidate: Callable[[str], bool],
) -> Optional[Tuple[float, float]]:
    query = str(name or "").strip()
    if not is_meaningful_place_candidate(query):
        return None
    record_metric("wikidata_requests")
    for language in ("zh", "en"):
        search_url = WIKIDATA_SEARCH_ENDPOINT.format(
            language=quote_text(language),
            query=quote_text(query),
        )
        payload = fetch_json(search_url)
        if not isinstance(payload, dict):
            continue
        items = payload.get("search") or []
        if not isinstance(items, list):
            continue
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get("id") or "").strip()
            if not entity_id:
                continue
            description = str(item.get("description") or "").strip()
            if _looks_like_non_place_description(description):
                continue
            if description and not _looks_like_place_description(description):
                continue
            entity_url = WIKIDATA_ENTITY_ENDPOINT.format(entity_id=quote_text(entity_id))
            entity_payload = fetch_json(entity_url)
            if not isinstance(entity_payload, dict):
                continue
            entities = entity_payload.get("entities") or {}
            entity = entities.get(entity_id) if isinstance(entities, dict) else None
            claims = entity.get("claims") if isinstance(entity, dict) else None
            coord_claims = claims.get("P625") if isinstance(claims, dict) else None
            if not isinstance(coord_claims, list) or not coord_claims:
                continue
            for claim in coord_claims:
                mainsnak = claim.get("mainsnak") if isinstance(claim, dict) else None
                datavalue = mainsnak.get("datavalue") if isinstance(mainsnak, dict) else None
                value = datavalue.get("value") if isinstance(datavalue, dict) else None
                if not isinstance(value, dict):
                    continue
                lat = value.get("latitude")
                lon = value.get("longitude")
                if is_valid_coord(lat, lon):
                    record_metric("wikidata_successes")
                    return float(lat), float(lon)
    record_metric("wikidata_failures")
    return None


def geocode_nominatim(
    name: str,
    *,
    force_cn: bool,
    fetch_json: Callable[..., Optional[object]],
    quote_text: Callable[[str], str],
    timeout_seconds: int,
    record_metric: Callable[[str], None],
    is_inside_china: Callable[[object, object], bool],
    endpoints: Sequence[Tuple[str, str]] = DEFAULT_ENDPOINTS,
    mapsco_api_key: str = "",
) -> Optional[Tuple[float, float]]:
    query = str(name or "").strip()
    if not query:
        return None
    record_metric("nominatim_requests")
    country_param = "&countrycodes=cn" if force_cn else ""
    for url_template, kind in endpoints:
        if "geocode.maps.co" in url_template and not mapsco_api_key:
            continue
        if "geocode.maps.co" in url_template:
            url = f"{url_template.format(quote_text(query))}&api_key={quote_text(mapsco_api_key)}"
        else:
            url = url_template.format(quote_text(query))
        if kind == "list" and country_param:
            url = f"{url}{country_param}"
        payload = fetch_json(url, timeout=timeout_seconds)
        if kind == "list" and isinstance(payload, list) and payload:
            lat = _safe_float(payload[0].get("lat"))
            lon = _safe_float(payload[0].get("lon"))
            if lat is not None and lon is not None and (not force_cn or is_inside_china(lat, lon)):
                record_metric("nominatim_successes")
                return lat, lon
        if kind == "photon" and isinstance(payload, dict):
            features = payload.get("features") or []
            if not features:
                continue
            geometry = features[0].get("geometry", {}) if isinstance(features[0], dict) else {}
            coords = geometry.get("coordinates") or []
            if len(coords) < 2:
                continue
            lon = _safe_float(coords[0])
            lat = _safe_float(coords[1])
            if lat is not None and lon is not None and (not force_cn or is_inside_china(lat, lon)):
                record_metric("nominatim_successes")
                return lat, lon
    record_metric("nominatim_failures")
    return None


def amap_webservice_geocode(
    address: str,
    *,
    amap_key: str,
    fetch_json: Callable[..., Optional[object]],
    quote_text: Callable[[str], str],
    timeout_seconds: int,
    record_metric: Callable[[str], None],
    is_valid_coord: Callable[[object, object], bool],
    gcj02_to_wgs84: Callable[[float, float], Tuple[float, float]],
) -> Optional[Tuple[float, float]]:
    query = str(address or "").strip()
    if not amap_key or not query:
        return None
    record_metric("amap_requests")
    url = f"https://restapi.amap.com/v3/geocode/geo?address={quote_text(query)}&key={quote_text(amap_key)}"
    payload = fetch_json(url, timeout=timeout_seconds)
    if not isinstance(payload, dict) or str(payload.get("status")) != "1":
        record_metric("amap_failures")
        return None
    geocodes = payload.get("geocodes")
    if not isinstance(geocodes, list) or not geocodes:
        record_metric("amap_failures")
        return None
    first = geocodes[0] if isinstance(geocodes[0], dict) else None
    if not isinstance(first, dict):
        record_metric("amap_failures")
        return None
    location = str(first.get("location") or "").strip()
    if not location or "," not in location:
        record_metric("amap_failures")
        return None
    lon_text, lat_text = location.split(",", 1)
    lat = _safe_float(lat_text)
    lon = _safe_float(lon_text)
    if lat is None or lon is None or not is_valid_coord(lat, lon):
        record_metric("amap_failures")
        return None
    record_metric("amap_successes")
    return gcj02_to_wgs84(lat, lon)


def resolve_city_geocode(
    name: str,
    *,
    build_candidates: Callable[[str], List[str]],
    looks_chinese: Callable[[str], bool],
    looks_foreign_location: Callable[[str], bool],
    cache_get: Callable[[str], Optional[Tuple[float, float]]],
    cache_set: Callable[[str, Tuple[float, float]], None],
    negative_cache_get: Callable[[str], Optional[Dict[str, object]]],
    negative_cache_set: Callable[[str], None],
    negative_cache_clear: Callable[..., None],
    record_metric: Callable[[str], None],
    amap_geocode: Callable[[str], Optional[Tuple[float, float]]],
    monid_geocode_enabled: Callable[[], bool],
    monid_geocode: Callable[[str], Optional[Tuple[float, float]]],
    wikidata_geocode: Callable[[str], Optional[Tuple[float, float]]],
    nominatim_geocode: Callable[[str, bool], Optional[Tuple[float, float]]],
) -> Optional[Tuple[float, float]]:
    query = str(name or "").strip()
    if not query:
        return None
    record_metric("lookups")
    candidates = build_candidates(query)
    looks_cn = looks_chinese(query)
    looks_foreign = looks_foreign_location(query)
    cached = cache_get(query)
    if cached:
        record_metric("cache_hits")
        return cached
    negative_cached = negative_cache_get(query)
    if negative_cached:
        record_metric("negative_cache_hits")
        return None
    record_metric("misses")
    if looks_cn and not looks_foreign:
        result = _try_candidates(candidates, amap_geocode)
        if result:
            return _finalize_success(query, result, candidates, cache_set, negative_cache_clear, record_metric)
    if monid_geocode_enabled():
        result = _try_candidates(candidates, monid_geocode)
        if result:
            return _finalize_success(query, result, candidates, cache_set, negative_cache_clear, record_metric)
    if looks_foreign or not looks_cn:
        result = _try_candidates(candidates, wikidata_geocode)
        if result:
            return _finalize_success(query, result, candidates, cache_set, negative_cache_clear, record_metric)
    result = _try_candidates(candidates, lambda candidate: nominatim_geocode(candidate, looks_cn and not looks_foreign))
    if result:
        return _finalize_success(query, result, candidates, cache_set, negative_cache_clear, record_metric)
    if looks_cn and not looks_foreign:
        result = _try_candidates(candidates, wikidata_geocode)
        if result:
            return _finalize_success(query, result, candidates, cache_set, negative_cache_clear, record_metric)
        result = _try_candidates(candidates, lambda candidate: nominatim_geocode(candidate, False))
        if result:
            return _finalize_success(query, result, candidates, cache_set, negative_cache_clear, record_metric)
    negative_cache_set(query)
    record_metric("failures")
    return None


def default_mapsco_api_key() -> str:
    return str(os.getenv("MAPSCO_API_KEY") or "").strip()


def default_amap_key() -> str:
    return (
        (os.getenv("locaion_api") or "").strip()
        or (os.getenv("location_api") or "").strip()
        or (os.getenv("LOCATION_API") or "").strip()
        or (os.getenv("AMAP_WEBSERVICE_KEY") or "").strip()
        or (os.getenv("AMAP_WEB_SERVICE_KEY") or "").strip()
        or (os.getenv("AMAP_REST_KEY") or "").strip()
    )


def _try_candidates(
    candidates: List[str],
    geocode_fn: Callable[[str], Optional[Tuple[float, float]]],
) -> Optional[Tuple[str, Tuple[float, float]]]:
    for candidate in candidates:
        result = geocode_fn(candidate)
        if result:
            return candidate, result
    return None


def _finalize_success(
    query: str,
    result: Tuple[str, Tuple[float, float]],
    candidates: List[str],
    cache_set: Callable[[str, Tuple[float, float]], None],
    negative_cache_clear: Callable[..., None],
    record_metric: Callable[[str], None],
) -> Tuple[float, float]:
    matched_candidate, coord = result
    cache_set(query, coord)
    for candidate in candidates:
        cache_set(candidate, coord)
    negative_cache_clear(query, matched_candidate)
    record_metric("successes")
    return coord


def _looks_like_place_description(text: str) -> bool:
    value = str(text or "").lower()
    if not value:
        return False
    markers = (
        "城市", "首都", "城镇", "聚居地", "行政区", "地区", "省", "州", "郡", "县", "村",
        "岛", "湖", "河", "山", "港", "共和国", "联邦", "王国", "capital", "city", "town",
        "village", "municipality", "county", "province", "region", "state", "country",
        "island", "lake", "river", "mountain", "settlement",
    )
    return any(marker in value for marker in markers)


def _looks_like_non_place_description(text: str) -> bool:
    value = str(text or "").lower()
    if not value:
        return False
    markers = (
        "人物", "作家", "诗人", "哲学家", "皇帝", "国王", "演员", "歌手", "导演", "政治家",
        "学者", "human", "person", "writer", "poet", "philosopher", "actor", "singer",
        "politician", "scientist",
    )
    return any(marker in value for marker in markers)


def _safe_float(value: object) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return None
