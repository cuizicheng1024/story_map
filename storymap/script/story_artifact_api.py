from __future__ import annotations

from typing import Callable, Dict, List, Type


def create_artifact_api(
    *,
    artifact_export_service_cls: Type[object],
    build_geojson_for_profile: Callable[[Dict[str, object]], Dict[str, object]],
    build_csv_for_profile: Callable[[Dict[str, object]], str],
    build_geojson_for_multi: Callable[[List[Dict[str, object]]], Dict[str, object]],
    build_csv_for_multi: Callable[[List[Dict[str, object]]], str],
) -> Dict[str, Callable[..., object]]:
    artifact_exports = artifact_export_service_cls(
        build_geojson_for_profile=build_geojson_for_profile,
        build_csv_for_profile=build_csv_for_profile,
        build_geojson_for_multi=build_geojson_for_multi,
        build_csv_for_multi=build_csv_for_multi,
    )

    def ensure_profile_exports(
        profile: Dict[str, object],
        base_name: str,
        allow_cache: bool = True,
    ) -> Dict[str, str]:
        return artifact_exports.ensure_profile_exports(profile, base_name, allow_cache=allow_cache)

    def ensure_multi_exports(
        people: List[Dict[str, object]],
        base_name: str,
        allow_cache: bool = True,
    ) -> Dict[str, str]:
        return artifact_exports.ensure_multi_exports(people, base_name, allow_cache=allow_cache)

    return {
        "ensure_profile_exports": ensure_profile_exports,
        "ensure_multi_exports": ensure_multi_exports,
    }
