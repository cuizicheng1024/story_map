from __future__ import annotations

from typing import Callable

from ...core import parsers as parser_utils


def enrich_markdown_for_map(
    md: str,
    *,
    normalize_markdown_tables: Callable[[str], str],
    geocode_markdown: Callable[[str], str],
    compute_total_distance_km: Callable[[str], object],
    insert_distance_intro: Callable[[str, float], str],
) -> str:
    if not isinstance(md, str):
        return ""
    enriched = normalize_markdown_tables(md)
    enriched = parser_utils.normalize_basic_info_birth_death_fields(enriched)
    enriched = geocode_markdown(enriched)
    distance_km = compute_total_distance_km(enriched)
    if isinstance(distance_km, float):
        enriched = insert_distance_intro(enriched, distance_km)
    return enriched


def generate_markdown_with_retry(*, client: object, person: str, generate_historical_markdown, progress, logger: object, retry_runner):
    return retry_runner(
        client=client,
        person=person,
        generate_historical_markdown=generate_historical_markdown,
        progress=progress,
        logger=logger,
    )
