from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(slots=True)
class BasicInfo:
    name: str = ""
    dynasty: str = ""
    birth_text: str = ""
    death_text: str = ""
    lifespan: str = ""
    identity: str = ""
    status: str = ""
    achievements: str = ""
    raw: Dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class LocationEntry:
    name: str = ""
    location_text: str = ""
    location_type: str = "normal"
    time: str = ""
    event: str = ""
    significance: str = ""
    duration: str = ""
    quotes: str = ""

    def to_legacy_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "type": self.location_type,
            "time": self.time,
            "location": self.location_text,
            "event": self.event,
            "significance": self.significance,
            "duration": self.duration,
            "quotes": self.quotes,
        }


@dataclass(slots=True)
class ParsedStoryDocument:
    raw_markdown: str
    normalized_markdown: str
    basic_info_map: Dict[str, str] = field(default_factory=dict)
    basic_info: BasicInfo = field(default_factory=BasicInfo)
    overview: str = ""
    timeline_header: List[str] = field(default_factory=list)
    timeline_rows: List[List[str]] = field(default_factory=list)
    places: List[Dict[str, str]] = field(default_factory=list)
    events: List[Dict[str, str]] = field(default_factory=list)
    location_sections: List[LocationEntry] = field(default_factory=list)
    coords_table: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    coords_search_map: Dict[str, str] = field(default_factory=dict)
    textbook_points: str = ""
    exam_points: str = ""
    historical_reviews: List[str] = field(default_factory=list)
