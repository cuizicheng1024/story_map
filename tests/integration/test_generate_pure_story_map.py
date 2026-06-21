import argparse
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


from tests_support import REPO_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _touch(path: Path, ts: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    os.utime(path, (ts, ts))


def test_scan_people_from_story_md_filters_placeholder_names(tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")
    (story_dir / "人物 生平传记与足迹.md").write_text("# 占位\n", encoding="utf-8")

    people = module._scan_people_from_story_md(story_dir)

    assert people == {"李白"}


def test_scan_people_from_story_md_filters_non_authentic_markdown(tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")
    (story_dir / "奥楚蔑洛夫.md").write_text("# 奥楚蔑洛夫 文学虚构人物\n\n并非真实历史人物。\n", encoding="utf-8")

    people = module._scan_people_from_story_md(story_dir)

    assert people == {"苏轼"}


def test_generate_pure_html_rejects_non_authentic_markdown(tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    md_path = tmp_path / "嫦娥.md"
    md_path.write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="人物真实性过滤拦截"):
        module.generate_pure_html(str(md_path), out_path=str(tmp_path / "嫦娥.html"))


def test_changed_people_rebuilds_when_profile_builder_is_newer(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    root = tmp_path / "repo"
    md_dir = tmp_path / "story"
    html_dir = tmp_path / "html"

    _touch(root / "storymap" / "script" / "map_html_renderer.py", 10)
    _touch(root / "storymap" / "script" / "profile_builder.py", 30)
    _touch(root / "storymap" / "script" / "story_map.py", 10)
    _touch(root / "storymap" / "script" / "templates" / "profile_page.html", 10)
    _touch(root / "cli" / "generate_pure_story_map.py", 10)
    _touch(md_dir / "苏轼.md", 15)
    _touch(html_dir / "苏轼.html", 20)

    monkeypatch.setattr(module, "_repo_root", lambda: str(root))

    changed = module._changed_people(md_dir, html_dir)

    assert changed == [("苏轼", "template_newer")]


def test_changed_people_rebuilds_when_design_tokens_css_is_newer(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    root = tmp_path / "repo"
    md_dir = tmp_path / "story"
    html_dir = tmp_path / "html"

    _touch(root / "storymap" / "script" / "map_html_renderer.py", 10)
    _touch(root / "storymap" / "script" / "profile_builder.py", 10)
    _touch(root / "storymap" / "script" / "story_map.py", 10)
    _touch(root / "storymap" / "script" / "templates" / "profile_page.html", 10)
    _touch(root / "storymap" / "script" / "templates" / "design_tokens.css", 30)
    _touch(root / "cli" / "generate_pure_story_map.py", 10)
    _touch(md_dir / "苏轼.md", 15)
    _touch(html_dir / "苏轼.html", 20)

    monkeypatch.setattr(module, "_repo_root", lambda: str(root))

    changed = module._changed_people(md_dir, html_dir)

    assert changed == [("苏轼", "template_newer")]


def test_changed_people_rebuilds_when_shared_person_registry_is_newer(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    root = tmp_path / "repo"
    md_dir = tmp_path / "story"
    html_dir = tmp_path / "html"

    _touch(root / "storymap" / "script" / "map_html_renderer.py", 10)
    _touch(root / "storymap" / "script" / "parsers.py", 10)
    _touch(root / "storymap" / "script" / "person_registry.py", 30)
    _touch(root / "storymap" / "script" / "person_tooltip_js.py", 10)
    _touch(root / "storymap" / "script" / "profile_builder.py", 10)
    _touch(root / "storymap" / "script" / "story_map.py", 10)
    _touch(root / "storymap" / "script" / "templates" / "profile_page.html", 10)
    _touch(root / "cli" / "generate_pure_story_map.py", 10)
    _touch(md_dir / "苏轼.md", 15)
    _touch(html_dir / "苏轼.html", 20)

    monkeypatch.setattr(module, "_repo_root", lambda: str(root))

    changed = module._changed_people(md_dir, html_dir)

    assert changed == [("苏轼", "template_newer")]


def test_changed_people_rebuilds_when_signature_is_stale_even_if_html_is_newer(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    root = tmp_path / "repo"
    md_dir = tmp_path / "story"
    html_dir = tmp_path / "html"

    _touch(root / "storymap" / "script" / "map_html_renderer.py", 10)
    _touch(root / "storymap" / "script" / "parsers.py", 10)
    _touch(root / "storymap" / "script" / "person_registry.py", 10)
    _touch(root / "storymap" / "script" / "person_tooltip_js.py", 10)
    _touch(root / "storymap" / "script" / "profile_builder.py", 10)
    _touch(root / "storymap" / "script" / "story_map.py", 10)
    _touch(root / "storymap" / "script" / "templates" / "profile_page.html", 10)
    _touch(root / "storymap" / "script" / "templates" / "design_tokens.css", 10)
    _touch(root / "cli" / "generate_pure_story_map.py", 10)
    _touch(md_dir / "苏轼.md", 15)
    html_path = html_dir / "苏轼.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(
        '<html><script>const data = {"person":{"name":"苏轼"},"templateSignature":"old-sign"};window.__EXPORT_DATA__ = data;</script></html>',
        encoding="utf-8",
    )
    os.utime(html_path, (40, 40))

    monkeypatch.setattr(module, "_repo_root", lambda: str(root))
    monkeypatch.setattr(module, "_current_profile_signature", lambda: "new-sign")

    changed = module._changed_people(md_dir, html_dir)

    assert changed == [("苏轼", "template_newer")]


def test_render_all_people_html_defaults_to_nogeocode(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: {"苏轼"})

    def fake_render(people, *, md_dir, html_dir, mode, allow_cache):
        captured["people"] = people
        captured["md_dir"] = md_dir
        captured["html_dir"] = html_dir
        captured["mode"] = mode
        captured["allow_cache"] = allow_cache
        return 0

    monkeypatch.setattr(module, "_render_people", fake_render)
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    assert module.render_all_people_html() == 0
    assert captured["people"] == ["苏轼"]
    assert captured["mode"] == "nogeocode"
    assert captured["allow_cache"] is False
    assert captured["alias_sync"] == tmp_path / "html"


def test_render_all_people_html_refreshes_homepage_once_in_cache_mode(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: {"苏轼"})

    def fake_render(people, *, md_dir, html_dir, mode, allow_cache):
        _ = (md_dir, html_dir)
        captured["people"] = people
        captured["mode"] = mode
        captured["allow_cache"] = allow_cache
        return 0

    monkeypatch.setattr(module, "_render_people", fake_render)
    monkeypatch.setattr(
        module,
        "_refresh_homepage_once",
        lambda: (captured.__setitem__("homepage_refresh", captured.get("homepage_refresh", 0) + 1), True)[1],
    )
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    assert module.render_all_people_html(mode="cache") == 0
    assert captured["people"] == ["苏轼"]
    assert captured["mode"] == "cache"
    assert captured["allow_cache"] is False
    assert captured["homepage_refresh"] == 1
    assert captured["alias_sync"] == tmp_path / "html"


def test_render_missing_people_html_defaults_to_nogeocode(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: {"苏轼"})
    monkeypatch.setattr(module, "_scan_people_from_story_map_html", lambda _dir: set())

    def fake_render(people, *, md_dir, html_dir, mode, allow_cache):
        _ = (md_dir, html_dir)
        captured["people"] = people
        captured["mode"] = mode
        captured["allow_cache"] = allow_cache
        return 0

    monkeypatch.setattr(module, "_render_people", fake_render)
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    assert module.render_missing_people_html() == 0
    assert captured["people"] == ["苏轼"]
    assert captured["mode"] == "nogeocode"
    assert captured["allow_cache"] is True
    assert captured["alias_sync"] == tmp_path / "html"


def test_scan_people_from_story_map_html_ignores_alias_redirect_stub(tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    html_dir = tmp_path / "html"
    html_dir.mkdir(parents=True)
    (html_dir / "苏轼.html").write_text(
        '<html><script>const data = {"person":{"name":"苏轼"}};window.__EXPORT_DATA__ = data;</script></html>',
        encoding="utf-8",
    )
    (html_dir / "苏东坡.html").write_text(
        "<html><script>window.location.replace('./%E8%8B%8F%E8%BD%BC.html')</script></html>",
        encoding="utf-8",
    )

    people = module._scan_people_from_story_map_html(html_dir)

    assert people == {"苏轼"}


def test_render_missing_people_html_rebuilds_when_only_alias_redirect_html_exists(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: {"苏东坡"})
    monkeypatch.setattr(module, "_scan_people_from_story_map_html", lambda _dir: set())

    def fake_render(people, *, md_dir, html_dir, mode, allow_cache):
        _ = (md_dir, html_dir)
        captured["people"] = people
        captured["mode"] = mode
        captured["allow_cache"] = allow_cache
        return 0

    monkeypatch.setattr(module, "_render_people", fake_render)
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    assert module.render_missing_people_html() == 0
    assert captured["people"] == ["苏东坡"]
    assert captured["mode"] == "nogeocode"
    assert captured["allow_cache"] is True
    assert captured["alias_sync"] == tmp_path / "html"


def test_render_changed_people_html_defaults_to_nogeocode(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_changed_people", lambda _md_dir, _html_dir: [("苏轼", "template_newer")])

    def fake_render(people, *, md_dir, html_dir, mode, allow_cache):
        captured["people"] = people
        captured["md_dir"] = md_dir
        captured["html_dir"] = html_dir
        captured["mode"] = mode
        captured["allow_cache"] = allow_cache
        return 0

    monkeypatch.setattr(module, "_render_people", fake_render)
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    assert module.render_changed_people_html() == 0
    assert captured["people"] == ["苏轼"]
    assert captured["mode"] == "nogeocode"
    assert captured["allow_cache"] is False
    assert captured["alias_sync"] == tmp_path / "html"


def test_render_changed_people_html_still_syncs_alias_redirects_when_nothing_changed(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_changed_people", lambda _md_dir, _html_dir: [])
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    assert module.render_changed_people_html() == 0
    assert captured["alias_sync"] == tmp_path / "html"


def test_main_render_all_falls_back_to_nogeocode_when_mode_is_empty(monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            md=None,
            person=None,
            out=None,
            render_missing=False,
            render_all=True,
            render_changed=False,
            missing_limit=0,
            missing_mode="pure",
            all_mode="",
            changed_mode="pure",
            changed_limit=0,
            no_geocode=False,
            no_browser=True,
        ),
    )
    def fake_render_all(*, mode):
        captured["mode"] = mode
        return 0

    monkeypatch.setattr(module, "render_all_people_html", fake_render_all)

    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured["mode"] == "nogeocode"


def test_generate_pure_html_syncs_alias_redirect_pages(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")

    md_path = tmp_path / "苏轼.md"
    md_path.write_text("# 苏轼\n", encoding="utf-8")
    out_path = tmp_path / "苏轼.html"
    captured = {}

    monkeypatch.setattr(module, "_add_import_paths", lambda: None)
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path))

    class FakeStoryMap:
        @staticmethod
        def load_profile_from_md(_md, allow_geocode=True):
            _ = allow_geocode
            return {"person": {"name": "苏轼"}}

    class FakeRenderer:
        @staticmethod
        def render_profile_html(_profile):
            return "<html>ok</html>"

    monkeypatch.setitem(sys.modules, "story_map", FakeStoryMap)
    monkeypatch.setitem(sys.modules, "map_html_renderer", FakeRenderer)
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    result = module.generate_pure_html(str(md_path), out_path=str(out_path), no_geocode=False)

    assert result["html_path"] == str(out_path)
    assert captured["alias_sync"] == tmp_path


def test_sync_alias_redirect_pages_keeps_dynamic_empty_redirects(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")

    class FakeHomepage:
        PERSON_PAGE_REDIRECTS = {"苏东坡": "苏轼"}

        @staticmethod
        def _render_person_alias_redirect_html(alias, canonical):
            return f"{alias}->{canonical}"

    monkeypatch.setattr(module, "_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: {"苏轼", "苏东坡"})
    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setitem(sys.modules, "tools.build_stellar_homepage", FakeHomepage)

    module._sync_alias_redirect_pages(tmp_path / "html")

    assert not (tmp_path / "html" / "苏东坡.html").exists()


def test_render_people_disables_per_person_homepage_refresh_in_cache_mode(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "_add_import_paths", lambda: None)

    class FakeStoryMap:
        @staticmethod
        def generate_for_person(**kwargs):
            captured.update(kwargs)
            return {"ok": True}

    sys.modules["story_map"] = FakeStoryMap

    rc = module._render_people(["苏轼"], md_dir=tmp_path, html_dir=tmp_path, mode="cache", allow_cache=False)

    assert rc == 0
    assert captured["person"] == "苏轼"
    assert captured["allow_cache"] is False
    assert captured["refresh_homepage"] is False


def test_render_people_marks_degraded_cache_results_as_failure(monkeypatch, tmp_path, capsys):
    module = importlib.import_module("cli.generate_pure_story_map")

    monkeypatch.setattr(module, "_add_import_paths", lambda: None)

    class FakeStoryMap:
        @staticmethod
        def generate_for_person(**_kwargs):
            return {"ok": False, "status": "degraded", "warning": "重要地点段落缺失或为空"}

    sys.modules["story_map"] = FakeStoryMap

    rc = module._render_people(["苏轼"], md_dir=tmp_path, html_dir=tmp_path, mode="cache", allow_cache=False)

    out = capsys.readouterr().out
    assert rc == 2
    assert "WARN 苏轼" in out
    assert "degraded=1" in out


def test_render_all_people_html_fails_when_homepage_refresh_fails_in_cache_mode(tmp_path, monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "story_md_dir_path", lambda: tmp_path / "story")
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: {"苏轼"})
    monkeypatch.setattr(module, "_render_people", lambda *args, **kwargs: 0)
    monkeypatch.setattr(module, "_refresh_homepage_once", lambda: False)
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    assert module.render_all_people_html(mode="cache") == 2
    assert captured["alias_sync"] == tmp_path / "html"


def test_accept_person_html_writes_canonical_person_page(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "_default_md_path", lambda person: str(tmp_path / f"{person}.md"))
    monkeypatch.setattr(module, "_canonical_html_path", lambda person: str(tmp_path / f"{person}.html"))

    def fake_generate(md_path, out_path=None, *, no_geocode=False):
        captured["md_path"] = md_path
        captured["out_path"] = out_path
        captured["no_geocode"] = no_geocode
        return {"html_path": out_path, "duration": {"total": "1.0ms"}}

    monkeypatch.setattr(module, "generate_pure_html", fake_generate)

    result = module.accept_person_html("苏轼", mode="pure", no_browser=True)

    assert result["html_path"] == str(tmp_path / "苏轼.html")
    assert captured["md_path"] == str(tmp_path / "苏轼.md")
    assert captured["out_path"] == str(tmp_path / "苏轼.html")
    assert captured["no_geocode"] is False


def test_accept_person_html_prefers_real_story_source_over_alias_redirect(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(module, "_default_md_path", lambda person: str(tmp_path / f"{person}.md"))
    monkeypatch.setattr(module, "_canonical_html_path", lambda person: str(tmp_path / f"{person}.html"))
    monkeypatch.setattr(module, "_scan_people_from_story_md", lambda _dir: {"苏轼", "苏东坡"})

    def fake_generate(md_path, out_path=None, *, no_geocode=False):
        captured["md_path"] = md_path
        captured["out_path"] = out_path
        captured["no_geocode"] = no_geocode
        return {"html_path": out_path, "duration": {"total": "1.0ms"}}

    monkeypatch.setattr(module, "generate_pure_html", fake_generate)

    result = module.accept_person_html("苏东坡", mode="pure", no_browser=True)

    assert result["html_path"] == str(tmp_path / "苏东坡.html")
    assert captured["md_path"] == str(tmp_path / "苏东坡.md")
    assert captured["out_path"] == str(tmp_path / "苏东坡.html")
    assert captured["no_geocode"] is False


def test_accept_person_html_cache_mode_refreshes_homepage_once(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")

    monkeypatch.setattr(module, "_canonical_html_path", lambda person: str(tmp_path / f"{person}.html"))
    monkeypatch.setattr(module, "story_md_dir_path", lambda: story_dir)
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))

    def fake_render(people, *, md_dir, html_dir, mode, allow_cache):
        captured["people"] = people
        captured["md_dir"] = md_dir
        captured["html_dir"] = html_dir
        captured["mode"] = mode
        captured["allow_cache"] = allow_cache
        return 0

    monkeypatch.setattr(module, "_render_people", fake_render)
    monkeypatch.setattr(
        module,
        "_refresh_homepage_once",
        lambda: (captured.__setitem__("homepage_refresh", captured.get("homepage_refresh", 0) + 1), True)[1],
    )
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda html_dir: captured.setdefault("alias_sync", html_dir))

    result = module.accept_person_html("苏轼", mode="cache", no_browser=True)

    assert result["html_path"] == str(tmp_path / "苏轼.html")
    assert captured["people"] == ["苏轼"]
    assert captured["mode"] == "cache"
    assert captured["allow_cache"] is False
    assert captured["homepage_refresh"] == 1
    assert captured["alias_sync"] == tmp_path / "html"


def test_accept_person_html_cache_mode_fails_when_homepage_refresh_fails(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")

    monkeypatch.setattr(module, "_canonical_html_path", lambda person: str(tmp_path / f"{person}.html"))
    monkeypatch.setattr(module, "story_md_dir_path", lambda: story_dir)
    monkeypatch.setattr(module, "_story_artifacts_dir", lambda: str(tmp_path / "html"))
    monkeypatch.setattr(module, "_render_people", lambda *args, **kwargs: 0)
    monkeypatch.setattr(module, "_refresh_homepage_once", lambda: False)
    monkeypatch.setattr(module, "_sync_alias_redirect_pages", lambda _html_dir: None)

    with pytest.raises(RuntimeError, match="首页刷新失败"):
        module.accept_person_html("苏轼", mode="cache", no_browser=True)


def test_accept_person_html_rejects_non_authentic_person_in_cache_mode(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n\n并非真实历史人物。\n", encoding="utf-8")

    monkeypatch.setattr(module, "story_md_dir_path", lambda: story_dir)
    monkeypatch.setattr(module, "_canonical_html_path", lambda person: str(tmp_path / f"{person}.html"))

    with pytest.raises(RuntimeError, match="人物真实性过滤拦截"):
        module.accept_person_html("嫦娥", mode="cache", no_browser=True)


def test_accept_person_html_rejects_unknown_person_in_cache_mode(monkeypatch, tmp_path):
    module = importlib.import_module("cli.generate_pure_story_map")
    story_dir = tmp_path / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "苏轼.md").write_text("# 苏轼\n", encoding="utf-8")

    monkeypatch.setattr(module, "story_md_dir_path", lambda: story_dir)
    monkeypatch.setattr(module, "_canonical_html_path", lambda person: str(tmp_path / f"{person}.html"))

    with pytest.raises(RuntimeError, match="人物真实性过滤拦截"):
        module.accept_person_html("海绵宝宝", mode="cache", no_browser=True)


def test_impact_render_html_delegates_to_render_changed(monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    def fake_render_changed(*, mode, max_people):
        captured["mode"] = mode
        captured["max_people"] = max_people
        return 0

    monkeypatch.setattr(module, "render_changed_people_html", fake_render_changed)

    assert module.impact_render_html(mode="cache", max_people=7) == 0
    assert captured == {"mode": "cache", "max_people": 7}


def test_publish_all_html_delegates_to_render_all(monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    def fake_render_all(*, mode):
        captured["mode"] = mode
        return 0

    monkeypatch.setattr(module, "render_all_people_html", fake_render_all)

    assert module.publish_all_html(mode="nogeocode") == 0
    assert captured == {"mode": "nogeocode"}


def test_main_accept_person_uses_accept_mode(monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            md=None,
            person=None,
            out=None,
            render_missing=False,
            render_all=False,
            render_changed=False,
            accept_person="苏轼",
            accept_mode="cache",
            impact_render=False,
            impact_mode="pure",
            publish_all=False,
            publish_mode="pure",
            missing_limit=0,
            missing_mode="pure",
            all_mode="pure",
            changed_mode="pure",
            changed_limit=0,
            no_geocode=False,
            no_browser=True,
        ),
    )

    def fake_accept(person, *, mode, no_browser):
        captured["person"] = person
        captured["mode"] = mode
        captured["no_browser"] = no_browser
        return {"html_path": "/tmp/苏轼.html", "duration": {}}

    monkeypatch.setattr(module, "accept_person_html", fake_accept)

    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured == {"person": "苏轼", "mode": "cache", "no_browser": True}


def test_main_impact_render_uses_impact_mode(monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            md=None,
            person=None,
            out=None,
            render_missing=False,
            render_all=False,
            render_changed=False,
            accept_person=None,
            accept_mode="pure",
            impact_render=True,
            impact_mode="cache",
            publish_all=False,
            publish_mode="pure",
            missing_limit=0,
            missing_mode="pure",
            all_mode="pure",
            changed_mode="pure",
            changed_limit=5,
            no_geocode=False,
            no_browser=True,
        ),
    )

    def fake_impact(*, mode, max_people):
        captured["mode"] = mode
        captured["max_people"] = max_people
        return 0

    monkeypatch.setattr(module, "impact_render_html", fake_impact)

    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured == {"mode": "cache", "max_people": 5}


def test_main_publish_all_uses_publish_mode(monkeypatch):
    module = importlib.import_module("cli.generate_pure_story_map")
    captured = {}

    monkeypatch.setattr(
        argparse.ArgumentParser,
        "parse_args",
        lambda self: SimpleNamespace(
            md=None,
            person=None,
            out=None,
            render_missing=False,
            render_all=False,
            render_changed=False,
            accept_person=None,
            accept_mode="pure",
            impact_render=False,
            impact_mode="pure",
            publish_all=True,
            publish_mode="nogeocode",
            missing_limit=0,
            missing_mode="pure",
            all_mode="pure",
            changed_mode="pure",
            changed_limit=0,
            no_geocode=False,
            no_browser=True,
        ),
    )

    def fake_publish(*, mode):
        captured["mode"] = mode
        return 0

    monkeypatch.setattr(module, "publish_all_html", fake_publish)

    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0

    assert captured == {"mode": "nogeocode"}
