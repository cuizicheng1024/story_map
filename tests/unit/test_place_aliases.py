import sys


from tests_support import REPO_ROOT
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from storymap.script.map import geocode_service as gs
from storymap.script.cli import story_map as sm


def test_place_aliases_can_resolve_direct_coords_without_network(monkeypatch):
    monkeypatch.setattr(gs, "_PLACE_ALIASES", None)
    monkeypatch.setattr(gs, "_HISTORICAL_INDEX", {})
    monkeypatch.setattr(
        gs,
        "_tgaz_query",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call tgaz")),
    )
    monkeypatch.setattr(
        gs,
        "geocode_city",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call geocode_city")),
    )

    coord = sm.resolve_place_coord("北京清华园（今北京市海淀区清华大学）")

    assert coord is not None
    assert round(coord[0], 4) == 40.0030
    assert round(coord[1], 4) == 116.3269


def test_place_aliases_can_resolve_foreign_historical_places_without_network(monkeypatch):
    monkeypatch.setattr(gs, "_PLACE_ALIASES", None)
    monkeypatch.setattr(gs, "_HISTORICAL_INDEX", {})
    monkeypatch.setattr(
        gs,
        "_tgaz_query",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call tgaz")),
    )
    monkeypatch.setattr(
        gs,
        "geocode_city",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call geocode_city")),
    )

    island_coord = sm.resolve_place_coord("优卑亚岛")
    city_coord = sm.resolve_place_coord("哈尔基斯（优卑亚岛）")

    assert island_coord is not None
    assert round(island_coord[0], 4) == 38.5236
    assert round(island_coord[1], 4) == 23.8585
    assert city_coord is not None
    assert round(city_coord[0], 4) == 38.4667
    assert round(city_coord[1], 4) == 23.6000


def test_resolve_place_coord_skips_non_place_candidates_before_network(monkeypatch):
    monkeypatch.setattr(gs, "_PLACE_ALIASES", {})
    monkeypatch.setattr(gs, "lookup_coords_from_historical_index", lambda *_args: None)
    monkeypatch.setattr(gs, "_tgaz_query", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        gs,
        "geocode_city",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not call geocode_city for rejected candidates")),
    )

    coord = gs.resolve_place_coord("不详", None, "中国去世", "具体位置待考")

    assert coord is None
