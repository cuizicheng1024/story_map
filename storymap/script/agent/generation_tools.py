from __future__ import annotations

from typing import Callable, Dict, List

from ..cli.tooling import tool


def create_generation_tools(
    *,
    append_coords_section: Callable[[str], str],
    parse_places: Callable[[str], List[Dict[str, str]]],
    parse_events: Callable[[str], List[Dict[str, str]]],
    build_points: Callable[..., List[Dict[str, object]]],
    collect_quality_metrics: Callable[[str], Dict[str, int]],
    validate_data_quality: Callable[[str], List[str]],
    print_quality_report: Callable[[str], None],
) -> Dict[str, Callable[..., object]]:
    @tool(name="geocode_markdown", description="为人物 Markdown 补齐地点坐标与地理编码信息")
    def geocode_markdown(md: str) -> str:
        return append_coords_section(md)

    @tool(name="parse_story_markdown", description="把人物 Markdown 解析为地点、事件与地图点位")
    def parse_story_markdown(md: str) -> Dict[str, object]:
        places = parse_places(md)
        events = parse_events(md)
        points = build_points(places, events)
        return {
            "places": places,
            "events": events,
            "points": points,
        }

    @tool(name="validate_story_markdown", description="校验人物 Markdown 的时间线、地点与坐标质量")
    def validate_story_markdown(md: str) -> Dict[str, object]:
        metrics = collect_quality_metrics(md)
        issues = validate_data_quality(md)
        print_quality_report(md)
        return {
            "metrics": metrics,
            "issues": issues,
        }

    return {
        "geocode_markdown": geocode_markdown,
        "parse_story_markdown": parse_story_markdown,
        "validate_story_markdown": validate_story_markdown,
    }
