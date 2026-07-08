import importlib

def test_person_registry_exposes_redirects_and_canonical_entries():
    module = importlib.import_module("storymap.script.core.person_registry")

    assert module.person_redirects()["苏东坡"] == "苏轼"
    assert module.person_redirects()["唐三藏"] == "玄奘"
    assert module.canonical_person_name("苏东坡") == "苏轼"
    assert module.canonical_person_name("唐三藏") == "玄奘"
    assert module.canonical_story_name_entries(["苏轼", "苏东坡", "李白"]) == [
        ("李白", "李白", []),
        ("苏东坡", "苏东坡", []),
        ("苏轼", "苏轼", []),
    ]
    assert module.canonical_story_name_entries(["苏轼"]) == [
        ("苏轼", "苏轼", ["苏东坡"]),
    ]
    assert module.canonical_story_name_entries(["玄奘"]) == [
        ("玄奘", "玄奘", ["唐三藏"]),
    ]

def test_person_redirects_skip_aliases_that_have_real_story_sources():
    module = importlib.import_module("storymap.script.core.person_registry")

    assert module.person_redirects(["苏轼", "苏东坡"]) == {}
    assert module.person_redirects(["苏轼"]) == {"苏东坡": "苏轼"}
    assert module.person_redirects(["玄奘", "唐三藏"]) == {}
    assert module.person_redirects(["玄奘"]) == {"唐三藏": "玄奘"}
    assert module.canonical_person_name("苏东坡", ["苏轼", "苏东坡"]) == "苏东坡"
    assert module.canonical_person_name("唐三藏", ["玄奘", "唐三藏"]) == "唐三藏"
    assert module.canonical_person_name("玛丽·居里", ["玛丽·居里"]) == "玛丽·居里"
    assert module.canonical_person_name("阿达·洛夫莱斯", ["阿达·洛夫莱斯"]) == "阿达·洛夫莱斯"

def test_map_html_renderer_uses_shared_person_registry():
    registry = importlib.import_module("storymap.script.core.person_registry")
    assert registry.canonical_person_name("苏东坡") == "苏轼"

def test_canonical_story_name_entries_preserve_raw_story_filenames_with_middle_dot():
    module = importlib.import_module("storymap.script.core.person_registry")

    entries = module.canonical_story_name_entries(["玛丽·居里", "马丁·路德·金"])

    assert entries == [
        ("玛丽·居里", "玛丽·居里", []),
        ("马丁·路德·金", "马丁·路德·金", []),
    ]
