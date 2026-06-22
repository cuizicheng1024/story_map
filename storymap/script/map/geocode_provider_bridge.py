from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from . import geocode_http as geocode_http_utils
from . import geocode_providers as geocode_provider_utils


def fetch_json(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    semaphore: object,
    rate_limit_fn: Callable[[], None],
    urlopen_fn: object,
    record_timeout: Callable[[], None],
) -> Optional[object]:
    return geocode_http_utils.fetch_json(
        url,
        user_agent=user_agent,
        timeout=max(1, int(timeout_seconds)),
        semaphore=semaphore,
        rate_limit_fn=rate_limit_fn,
        urlopen_fn=urlopen_fn,
        record_timeout=record_timeout,
    )


def post_json(
    url: str,
    payload: object,
    *,
    user_agent: str,
    timeout_seconds: int,
    semaphore: object,
    rate_limit_fn: Callable[[], None],
    urlopen_fn: object,
    record_timeout: Callable[[], None],
    headers: Optional[Dict[str, str]] = None,
) -> Optional[object]:
    return geocode_http_utils.post_json(
        url,
        payload,
        user_agent=user_agent,
        timeout=max(1, int(timeout_seconds)),
        semaphore=semaphore,
        rate_limit_fn=rate_limit_fn,
        urlopen_fn=urlopen_fn,
        record_timeout=record_timeout,
        headers=headers,
    )


def monid_geocode(
    name: str,
    *,
    api_key: str,
    post_json_fn: Callable[..., Optional[object]],
    timeout_seconds: int,
    record_metric: Callable[[str, int], None],
    is_valid_coord: Callable[[object, object], bool],
) -> Optional[Tuple[float, float]]:
    return geocode_provider_utils.monid_geocode(
        name,
        api_key=api_key,
        post_json=post_json_fn,
        timeout_seconds=timeout_seconds,
        record_metric=record_metric,
        is_valid_coord=is_valid_coord,
    )


def geocode_wikidata(
    name: str,
    *,
    fetch_json_fn: Callable[..., Optional[object]],
    quote_text: Callable[[str], str],
    record_metric: Callable[[str, int], None],
    is_valid_coord: Callable[[object, object], bool],
    is_meaningful_place_candidate: Callable[[str], bool],
) -> Optional[Tuple[float, float]]:
    return geocode_provider_utils.geocode_wikidata(
        name,
        fetch_json=fetch_json_fn,
        quote_text=quote_text,
        record_metric=record_metric,
        is_valid_coord=is_valid_coord,
        is_meaningful_place_candidate=is_meaningful_place_candidate,
    )


def geocode_nominatim(
    name: str,
    *,
    force_cn: bool,
    fetch_json_fn: Callable[..., Optional[object]],
    quote_text: Callable[[str], str],
    timeout_seconds: int,
    record_metric: Callable[[str, int], None],
    is_inside_china: Callable[[object, object], bool],
    mapsco_api_key: str,
) -> Optional[Tuple[float, float]]:
    return geocode_provider_utils.geocode_nominatim(
        name,
        force_cn=force_cn,
        fetch_json=fetch_json_fn,
        quote_text=quote_text,
        timeout_seconds=timeout_seconds,
        record_metric=record_metric,
        is_inside_china=is_inside_china,
        mapsco_api_key=mapsco_api_key,
    )


def amap_webservice_geocode(
    address: str,
    *,
    amap_key: str,
    fetch_json_fn: Callable[..., Optional[object]],
    quote_text: Callable[[str], str],
    timeout_seconds: int,
    record_metric: Callable[[str, int], None],
    is_valid_coord: Callable[[object, object], bool],
    gcj02_to_wgs84: Callable[[float, float], Tuple[float, float]],
) -> Optional[Tuple[float, float]]:
    return geocode_provider_utils.amap_webservice_geocode(
        address,
        amap_key=amap_key,
        fetch_json=fetch_json_fn,
        quote_text=quote_text,
        timeout_seconds=timeout_seconds,
        record_metric=record_metric,
        is_valid_coord=is_valid_coord,
        gcj02_to_wgs84=gcj02_to_wgs84,
    )
