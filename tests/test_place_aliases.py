import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO_ROOT / "storymap" / "script"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import geocode_service as gs
import story_map as sm


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
