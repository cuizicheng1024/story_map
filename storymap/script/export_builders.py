import csv
import io
from typing import Dict, List


def is_valid_coord(lat: object, lng: object) -> bool:
    try:
        lat_f = float(lat)
        lng_f = float(lng)
    except Exception:
        return False
    return abs(lat_f) <= 90 and abs(lng_f) <= 180


def build_geojson_for_profile(profile: Dict[str, object]) -> Dict[str, object]:
    person = profile.get("person") or {}
    locations = profile.get("locations") or []
    features = []
    coords = []
    for loc in locations:
        lat = loc.get("lat")
        lng = loc.get("lng")
        if not is_valid_coord(lat, lng):
            continue
        coords.append([lng, lat])
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
                "properties": {
                    "person": person.get("name", ""),
                    "name": loc.get("name", ""),
                    "type": loc.get("type", ""),
                    "time": loc.get("time", ""),
                    "modernName": loc.get("modernName", ""),
                    "ancientName": loc.get("ancientName", ""),
                },
            }
        )
    if len(coords) > 1:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"person": person.get("name", ""), "name": "轨迹"},
            }
        )
    return {"type": "FeatureCollection", "features": features}


def build_csv_for_profile(profile: Dict[str, object]) -> str:
    person = profile.get("person") or {}
    locations = profile.get("locations") or []
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["person", "name", "lat", "lng", "type", "time", "modernName", "ancientName"])
    for loc in locations:
        writer.writerow(
            [
                person.get("name", ""),
                loc.get("name", ""),
                loc.get("lat", ""),
                loc.get("lng", ""),
                loc.get("type", ""),
                loc.get("time", ""),
                loc.get("modernName", ""),
                loc.get("ancientName", ""),
            ]
        )
    return buffer.getvalue()


def build_geojson_for_multi(people: List[Dict[str, object]]) -> Dict[str, object]:
    features = []
    for item in people:
        person = item.get("person") or {}
        locations = item.get("locations") or []
        coords = []
        for loc in locations:
            lat = loc.get("lat")
            lng = loc.get("lng")
            if not is_valid_coord(lat, lng):
                continue
            coords.append([lng, lat])
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lng, lat]},
                    "properties": {
                        "person": person.get("name", ""),
                        "name": loc.get("name", ""),
                        "type": loc.get("type", ""),
                        "time": loc.get("time", ""),
                        "modernName": loc.get("modernName", ""),
                        "ancientName": loc.get("ancientName", ""),
                    },
                }
            )
        if len(coords) > 1:
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {"person": person.get("name", ""), "name": "轨迹"},
                }
            )
    return {"type": "FeatureCollection", "features": features}


def build_csv_for_multi(people: List[Dict[str, object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["person", "name", "lat", "lng", "type", "time", "modernName", "ancientName"])
    for item in people:
        person = item.get("person") or {}
        for loc in item.get("locations") or []:
            writer.writerow(
                [
                    person.get("name", ""),
                    loc.get("name", ""),
                    loc.get("lat", ""),
                    loc.get("lng", ""),
                    loc.get("type", ""),
                    loc.get("time", ""),
                    loc.get("modernName", ""),
                    loc.get("ancientName", ""),
                ]
            )
    return buffer.getvalue()
