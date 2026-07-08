from storymap.script.core.public_url import public_base_url, public_url


def test_public_base_url_accepts_https_domain(monkeypatch):
    monkeypatch.setenv("STORYMAP_PUBLIC_BASE_URL", "https://storymap.cn")

    assert public_base_url() == "https://storymap.cn/"
    assert public_url("./李白.html") == "https://storymap.cn/%E6%9D%8E%E7%99%BD.html"
    assert public_url("artifacts/story_map/李白.geojson") == "https://storymap.cn/%E6%9D%8E%E7%99%BD.geojson"


def test_public_base_url_ignores_invalid_value(monkeypatch):
    monkeypatch.setenv("STORYMAP_PUBLIC_BASE_URL", "storymap.cn")

    assert public_base_url() == ""
    assert public_url("./李白.html") == ""
