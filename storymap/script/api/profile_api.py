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
    submit_hard_place_review: Optional[Callable[[Dict[str, object]], Dict[str, object]]] = None,
    render_profile_html: Callable[..., str],
    build_info_panel_html: Callable[..., str],
    render_amap_html: Callable[..., str],
) -> Dict[str, Callable[..., object]]:
    import logging as _profile_api_logging
    _pa_logger = _profile_api_logging.getLogger(__name__)

    def _queue_unresolved_place(
        place_name: object,
        *,
        fallback_person: str = "",
        context: str = "",
        reason: str = "",
    ) -> None:
        if not callable(submit_hard_place_review):
            return
        normalized = str(place_name or "").strip()
        if not normalized:
            return
        try:
            submit_hard_place_review(
                {
                    "place_name": normalized,
                    "person": str(fallback_person or "").strip(),
                    "context": str(context or "").strip(),
                    "reason": str(reason or "profile_coord_unresolved").strip() or "profile_coord_unresolved",
                }
            )
        except Exception as exc:
            _pa_logger.warning(
                "queue_unresolved_place failed place=%s person=%s reason=%s: %s",
                normalized,
                str(fallback_person or "").strip(),
                str(reason or "profile_coord_unresolved").strip(),
                str(exc).strip() or type(exc).__name__,
            )

    def build_points(
        places: List[Dict[str, str]],
        events: List[Dict[str, str]],
        *,
        allow_geocode: bool = True,
        event_callback: Optional[callable] = None,
        fallback_person: str = "",
    ) -> List[Dict[str, object]]:
        def geocode_city_with_review(name: str) -> object:
            coord = geocode_city(name)
            if coord:
                return coord
            _queue_unresolved_place(
                name,
                fallback_person=fallback_person,
                context="build_points",
                reason="profile_build_points_geocode_failed",
            )
            return None

        return profile_builder_utils.build_points(
            places,
            events,
            allow_geocode=allow_geocode,
            lookup_coords_from_historical_index=lookup_coords_from_historical_index,
            geocode_city=geocode_city_with_review,
            event_callback=event_callback,
        )

    def extract_intro_fields(md: str) -> Dict[str, str]:
        return profile_builder_utils.extract_intro_fields(md)

    def build_profile_data(
        md: str,
        event_callback: Optional[callable] = None,
        *,
        fallback_person: str = "",
        allow_geocode: bool = True,
    ) -> Optional[Dict[str, object]]:
        def resolve_place_coord_with_review(place: str, year: Optional[int] = None, *aliases: object) -> object:
            coord = resolve_place_coord(place, year, *aliases)
            if coord:
                return coord
            alias_preview = " | ".join(str(item or "").strip() for item in aliases if str(item or "").strip())
            _queue_unresolved_place(
                place,
                fallback_person=fallback_person,
                context=f"build_profile_data year={year or ''} aliases={alias_preview[:120]}".strip(),
                reason="profile_resolve_place_coord_failed",
            )
            return None

        def build_points_for_profile(
            places: List[Dict[str, str]],
            events: List[Dict[str, str]],
            *,
            allow_geocode: bool = True,
            event_callback: Optional[callable] = None,
        ) -> List[Dict[str, object]]:
            return build_points(
                places,
                events,
                allow_geocode=allow_geocode,
                event_callback=event_callback,
                fallback_person=fallback_person,
            )

        return profile_builder_utils.build_profile_data(
            md,
            fallback_person=fallback_person,
            allow_geocode=allow_geocode,
            event_callback=event_callback,
            split_ancient_modern=split_ancient_modern,
            batch_split_ancient_modern=batch_split_ancient_modern,
            fuzzy_coord_lookup=fuzzy_coord_lookup,
            lookup_coords_from_historical_index=lookup_coords_from_historical_index,
            resolve_place_coord=resolve_place_coord_with_review,
            build_points_fn=build_points_for_profile,
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
        fallback_person: str = "",
        allow_geocode: bool = True,
    ) -> Optional[Dict[str, object]]:
        return build_profile_data(
            md,
            fallback_person=fallback_person,
            allow_geocode=allow_geocode,
            event_callback=event_callback,
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
        submit_hard_place_review=(
            (lambda payload: geocode_api["submit_hard_place_review"](payload))
            if "submit_hard_place_review" in geocode_api
            else None
        ),
        render_profile_html=render_profile_html,
        build_info_panel_html=build_info_panel_html,
        render_amap_html=render_amap_html,
    )
