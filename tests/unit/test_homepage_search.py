import importlib
import warnings

from tools.build import homepage_search

def test_build_search_fields_include_name_alias_and_foreign_name():
    fields = homepage_search.build_search_fields(
        "王昭君",
        ["明妃", "王嫱"],
        "Zhaojun Wang",
    )

    assert "王昭君" in fields["search_keys"]
    assert "明妃" in fields["search_keys"]
    assert "王嫱" in fields["search_keys"]
    assert "Zhaojun Wang" in fields["search_keys"]
    assert "王昭君" in fields["search_tokens"]
    assert "zhaojunwang" in fields["search_tokens"]

def test_normalize_search_text_strips_spacing_and_punctuation():
    assert homepage_search.normalize_search_text(" Zhaojun-Wang ") == "zhaojunwang"
    assert homepage_search.normalize_search_text("《王昭君》") == "王昭君"

def test_reload_homepage_search_suppresses_pypinyin_codecs_deprecation_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.reload(homepage_search)

    assert not any(
        isinstance(item.message, DeprecationWarning)
        and "codecs.open() is deprecated" in str(item.message)
        for item in caught
    )
