from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple


def create_geocode_api(*, geocode_service_utils: object) -> Dict[str, Callable[..., object]]:
    def lookup_coords_from_historical_index(*names: str) -> Optional[Tuple[float, float]]:
        return geocode_service_utils.lookup_coords_from_historical_index(*names)

    def resolve_place_coord(place: str, year: Optional[int] = None, *aliases: str) -> Optional[Tuple[float, float]]:
        return geocode_service_utils.resolve_place_coord(place, year, *aliases)

    def batch_split_ancient_modern(
        loc_texts: List[str], event_callback: Optional[callable] = None
    ) -> Dict[str, Tuple[str, str]]:
        return geocode_service_utils.batch_split_ancient_modern(
            loc_texts,
            event_callback=event_callback,
        )

    def split_ancient_modern(
        loc_text: str,
        event_callback: Optional[callable] = None,
    ) -> Tuple[str, str]:
        return geocode_service_utils.split_ancient_modern(
            loc_text,
            event_callback=event_callback,
        )

    def fuzzy_coord_lookup(
        coords_cache: Dict[str, Tuple[float, float]],
        candidates: List[str],
    ) -> Optional[Tuple[float, float]]:
        return geocode_service_utils.fuzzy_coord_lookup(coords_cache, candidates)

    return {
        "lookup_coords_from_historical_index": lookup_coords_from_historical_index,
        "resolve_place_coord": resolve_place_coord,
        "batch_split_ancient_modern": batch_split_ancient_modern,
        "split_ancient_modern": split_ancient_modern,
        "fuzzy_coord_lookup": fuzzy_coord_lookup,
    }
