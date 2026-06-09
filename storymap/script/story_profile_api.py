from __future__ import annotations

from typing import Callable, Dict, List, Optional


def create_profile_api(
    *,
    parser_utils: object,
    profile_builder_utils: object,
    generation_service_utils: object,
    geocode_city: Callable[..., object],
    lookup_coords_from_historical_index: Callable[..., object],
    resolve_place_coord: Callable[..., object],
    split_ancient_modern: Callable[..., object],
    batch_split_ancient_modern: Callable[..., object],
    fuzzy_coord_lookup: Callable[..., object],
    render_profile_html: Callable[..., str],
    build_info_panel_html: Callable[..., str],
    render_amap_html: Callable[..., str],
) -> Dict[str, Callable[..., object]]:
    def build_points(
        places: List[Dict[str, str]],
        events: List[Dict[str, str]],
        *,
        allow_geocode: bool = True,
        event_callback: Optional[callable] = None,
    ) -> List[Dict[str, object]]:
        return profile_builder_utils.build_points(
            places,
            events,
            allow_geocode=allow_geocode,
            lookup_coords_from_historical_index=lookup_coords_from_historical_index,
            geocode_city=geocode_city,
            event_callback=event_callback,
        )

    def extract_intro_fields(md: str) -> Dict[str, str]:
        return profile_builder_utils.extract_intro_fields(md)

    def build_profile_data(
        md: str,
        event_callback: Optional[callable] = None,
        *,
        allow_geocode: bool = True,
    ) -> Optional[Dict[str, object]]:
        return profile_builder_utils.build_profile_data(
            md,
            allow_geocode=allow_geocode,
            event_callback=event_callback,
            split_ancient_modern=split_ancient_modern,
            batch_split_ancient_modern=batch_split_ancient_modern,
            fuzzy_coord_lookup=fuzzy_coord_lookup,
            lookup_coords_from_historical_index=lookup_coords_from_historical_index,
            resolve_place_coord=resolve_place_coord,
            build_points_fn=build_points,
        )

    def parse_places(md: str) -> List[Dict[str, str]]:
        return parser_utils.parse_places(md)

    def parse_events(md: str) -> List[Dict[str, str]]:
        return parser_utils.parse_events(md)

    def render_html(title: str, points: List[Dict[str, object]], md: str = "") -> str:
        return generation_service_utils.render_html(
            title,
            points,
            md=md,
            build_profile_data=build_profile_data,
            extract_intro_fields=extract_intro_fields,
            render_profile_html=render_profile_html,
            build_info_panel_html=build_info_panel_html,
            render_amap_html=render_amap_html,
        )

    def load_profile_from_md(
        md: str,
        event_callback: Optional[callable] = None,
        *,
        allow_geocode: bool = True,
    ) -> Optional[Dict[str, object]]:
        return profile_builder_utils.load_profile_from_md(
            md,
            allow_geocode=allow_geocode,
            event_callback=event_callback,
            split_ancient_modern=split_ancient_modern,
            batch_split_ancient_modern=batch_split_ancient_modern,
            fuzzy_coord_lookup=fuzzy_coord_lookup,
            lookup_coords_from_historical_index=lookup_coords_from_historical_index,
            resolve_place_coord=resolve_place_coord,
            build_points_fn=build_points,
        )

    return {
        "build_profile_data": build_profile_data,
        "parse_places": parse_places,
        "parse_events": parse_events,
        "build_points": build_points,
        "extract_intro_fields": extract_intro_fields,
        "render_html": render_html,
        "load_profile_from_md": load_profile_from_md,
    }


def create_profile_api_from_geocode_api(
    *,
    parser_utils: object,
    profile_builder_utils: object,
    generation_service_utils: object,
    geocode_city: Callable[..., object],
    geocode_api: Dict[str, Callable[..., object]],
    render_profile_html: Callable[..., str],
    build_info_panel_html: Callable[..., str],
    render_amap_html: Callable[..., str],
) -> Dict[str, Callable[..., object]]:
    return create_profile_api(
        parser_utils=parser_utils,
        profile_builder_utils=profile_builder_utils,
        generation_service_utils=generation_service_utils,
        geocode_city=geocode_city,
        lookup_coords_from_historical_index=lambda *names: geocode_api["lookup_coords_from_historical_index"](*names),
        resolve_place_coord=lambda *args, **kwargs: geocode_api["resolve_place_coord"](*args, **kwargs),
        split_ancient_modern=lambda *args, **kwargs: geocode_api["split_ancient_modern"](*args, **kwargs),
        batch_split_ancient_modern=lambda *args, **kwargs: geocode_api["batch_split_ancient_modern"](*args, **kwargs),
        fuzzy_coord_lookup=lambda *args, **kwargs: geocode_api["fuzzy_coord_lookup"](*args, **kwargs),
        render_profile_html=render_profile_html,
        build_info_panel_html=build_info_panel_html,
        render_amap_html=render_amap_html,
    )
