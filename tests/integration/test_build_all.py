import importlib
import json
import sys
from pathlib import Path


from tests_support import REPO_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_build_all_generates_core_artifacts_for_minimal_story_set(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    for person in ("李白", "王昭君"):
        (story_dir / f"{person}.md").write_text(f"# {person}\n\n## 一、人物档案\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", story_map_dir / "stellar_home_data.json")
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", story_map_dir / "stellar_home_data_detail.json")
    monkeypatch.setattr(module, "MANIFEST_JSON", data_dir / "build_manifest.json")
    monkeypatch.setattr(module, "VALIDATION_JSON", data_dir / "build_validation_report.json")
    monkeypatch.setattr(module, "PERF_BASELINE_JSON", data_dir / "performance_baseline.json")
    monkeypatch.setattr(module, "MARKDOWN_SMOKE_JSON", data_dir / "markdown_smoke_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_JSON", data_dir / "low_coverage_story_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_MD", data_dir / "low_coverage_story_report.md")
    monkeypatch.setattr(module, "BAD_PERSON_NAMES", frozenset())
    monkeypatch.setattr(module, "_run_markdown_smoke_check", lambda _scope: 0)
    commands = []

    def _fake_run(cmd, cwd=None):
        _ = cwd
        commands.append(cmd)
        cmd_text = " ".join(cmd)
        if "tools/build_people_master.py" in cmd_text:
            out_path = Path(cmd[cmd.index("--out") + 1])
            payload = {
                "people": [
                    {"person": "李白", "has_story": False, "story_md": ""},
                    {"person": "王昭君", "has_story": False, "story_md": ""},
                ],
                "count": 2,
            }
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return 0
        if "cli/generate_pure_story_map.py" in cmd_text:
            for person in ("李白", "王昭君"):
                (story_map_dir / f"{person}.html").write_text(
                    (
                        "<html><script>const data = "
                        + json.dumps(
                            {"person": {"name": person}, "templateSignature": module.profile_template_signature()},
                            ensure_ascii=False,
                        )
                        + ";window.__EXPORT_DATA__ = data;</script></html>"
                    ),
                    encoding="utf-8",
                )
            return 0
        if "tools/build_people_summary_index.py" in cmd_text:
            (data_dir / "people_summary_index.json").write_text(
                json.dumps({"items": {"李白": {"review": "浪漫主义诗歌高峰。"}}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return 0
        if "tools/build_work_summary_index.py" in cmd_text:
            (data_dir / "work_summary_index.json").write_text(
                json.dumps({"items": {"将进酒": {"title": "将进酒", "authors": ["李白"]}}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return 0
        if "tools/build_stellar_homepage.py" in cmd_text:
            module.HOME_DATA.write_text(
                json.dumps(
                    {
                        "nodes": [
                            {"person": "李白", "file": "李白.html", "has_story": True, "birth_lat_wgs84": 30.0, "birth_lng_wgs84": 120.0},
                            {"person": "王昭君", "file": "王昭君.html", "has_story": True, "birth_lat_wgs84": 31.0, "birth_lng_wgs84": 121.0},
                        ]
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            module.HOME_DETAIL_DATA.write_text(
                json.dumps({"details": {"李白": {"review": "浪漫主义诗歌高峰。"}}}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (story_map_dir / "index.html").write_text("<html>index</html>", encoding="utf-8")
            (data_dir / "people_birth_coords_wgs84.json").write_text(
                json.dumps({"李白": [30.0, 120.0], "王昭君": [31.0, 121.0]}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return 0
        if "tools/report_low_coverage_places.py" in cmd_text:
            module.LOW_COVERAGE_JSON.write_text(json.dumps({"items": []}, ensure_ascii=False, indent=2), encoding="utf-8")
            module.LOW_COVERAGE_MD.write_text("# empty\n", encoding="utf-8")
            return 0
        raise AssertionError(f"unexpected command: {cmd_text}")

    monkeypatch.setattr(module, "_run", _fake_run)
    monkeypatch.setattr(sys, "argv", ["build_all.py", "--markdown-smoke-check", "off"])

    rc = module.main()

    assert rc == 0
    assert (data_dir / "people_master.json").exists()
    assert (data_dir / "work_summary_index.json").exists()
    assert (story_map_dir / "stellar_home_data.json").exists()
    assert (story_map_dir / "index.html").exists()
    assert (data_dir / "performance_baseline.json").exists()
    assert (story_map_dir / "李白.html").exists()
    assert (story_map_dir / "王昭君.html").exists()
    perf_payload = json.loads((data_dir / "performance_baseline.json").read_text(encoding="utf-8"))
    assert perf_payload["homepage_payload"]["nodes"] == 2
    assert perf_payload["homepage_payload"]["nodes_with_coords"] == 2
    assert perf_payload["files"]["stellar_home_data"]["exists"] is True
    assert perf_payload["files"]["stellar_home_data_detail"]["exists"] is True
    summary_index_idx = next(i for i, cmd in enumerate(commands) if "tools/build_people_summary_index.py" in " ".join(cmd))
    work_summary_index_idx = next(i for i, cmd in enumerate(commands) if "tools/build_work_summary_index.py" in " ".join(cmd))
    homepage_idx = next(i for i, cmd in enumerate(commands) if "tools/build_stellar_homepage.py" in " ".join(cmd))
    assert summary_index_idx < homepage_idx
    assert work_summary_index_idx < homepage_idx


def test_build_all_fails_fast_when_validation_report_has_errors(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", story_map_dir / "stellar_home_data.json")
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", story_map_dir / "stellar_home_data_detail.json")
    monkeypatch.setattr(module, "MANIFEST_JSON", data_dir / "build_manifest.json")
    monkeypatch.setattr(module, "VALIDATION_JSON", data_dir / "build_validation_report.json")
    monkeypatch.setattr(module, "PERF_BASELINE_JSON", data_dir / "performance_baseline.json")
    monkeypatch.setattr(module, "MARKDOWN_SMOKE_JSON", data_dir / "markdown_smoke_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_JSON", data_dir / "low_coverage_story_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_MD", data_dir / "low_coverage_story_report.md")
    monkeypatch.setattr(module, "BAD_PERSON_NAMES", frozenset())
    monkeypatch.setattr(module, "_run_markdown_smoke_check", lambda _scope: 0)
    monkeypatch.setattr(module, "_run", lambda cmd, cwd=None: 0)
    monkeypatch.setattr(module, "_patch_master_with_has_story", lambda _path: {"updated": 0, "total": 0})
    monkeypatch.setattr(module, "_patch_home_with_has_story", lambda _path: {"updated": 0, "total": 0})
    monkeypatch.setattr(module, "_build_manifest", lambda: {"ok": True})
    monkeypatch.setattr(module, "_build_validation_report", lambda: {"ok": False, "summary": {"error_count": 1, "warning_count": 0}})
    monkeypatch.setattr(sys, "argv", ["build_all.py", "--markdown-smoke-check", "off"])

    rc = module.main()

    assert rc == 2


def test_build_all_can_explicitly_allow_validation_errors(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", story_map_dir / "stellar_home_data.json")
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", story_map_dir / "stellar_home_data_detail.json")
    monkeypatch.setattr(module, "MANIFEST_JSON", data_dir / "build_manifest.json")
    monkeypatch.setattr(module, "VALIDATION_JSON", data_dir / "build_validation_report.json")
    monkeypatch.setattr(module, "PERF_BASELINE_JSON", data_dir / "performance_baseline.json")
    monkeypatch.setattr(module, "MARKDOWN_SMOKE_JSON", data_dir / "markdown_smoke_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_JSON", data_dir / "low_coverage_story_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_MD", data_dir / "low_coverage_story_report.md")
    monkeypatch.setattr(module, "BAD_PERSON_NAMES", frozenset())
    monkeypatch.setattr(module, "_run_markdown_smoke_check", lambda _scope: 0)
    monkeypatch.setattr(module, "_run", lambda cmd, cwd=None: 0)
    monkeypatch.setattr(module, "_patch_master_with_has_story", lambda _path: {"updated": 0, "total": 0})
    monkeypatch.setattr(module, "_patch_home_with_has_story", lambda _path: {"updated": 0, "total": 0})
    monkeypatch.setattr(module, "_build_manifest", lambda: {"ok": True})
    monkeypatch.setattr(module, "_build_validation_report", lambda: {"ok": False, "summary": {"error_count": 1, "warning_count": 0}})
    monkeypatch.setattr(sys, "argv", ["build_all.py", "--markdown-smoke-check", "off", "--allow-validation-errors"])

    rc = module.main()

    assert rc == 0


def test_build_all_uses_nogeocode_mode_for_changed_html_by_default(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", story_map_dir / "stellar_home_data.json")
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", story_map_dir / "stellar_home_data_detail.json")
    monkeypatch.setattr(module, "MANIFEST_JSON", data_dir / "build_manifest.json")
    monkeypatch.setattr(module, "VALIDATION_JSON", data_dir / "build_validation_report.json")
    monkeypatch.setattr(module, "PERF_BASELINE_JSON", data_dir / "performance_baseline.json")
    monkeypatch.setattr(module, "MARKDOWN_SMOKE_JSON", data_dir / "markdown_smoke_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_JSON", data_dir / "low_coverage_story_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_MD", data_dir / "low_coverage_story_report.md")
    monkeypatch.setattr(module, "BAD_PERSON_NAMES", frozenset())
    monkeypatch.setattr(module, "_run_markdown_smoke_check", lambda _scope: 0)
    monkeypatch.setattr(module, "_patch_master_with_has_story", lambda _path: {"updated": 0, "total": 0})
    monkeypatch.setattr(module, "_patch_home_with_has_story", lambda _path: {"updated": 0, "total": 0})
    monkeypatch.setattr(module, "_build_manifest", lambda: {"ok": True})
    monkeypatch.setattr(module, "_build_validation_report", lambda: {"ok": True, "summary": {"error_count": 0, "warning_count": 0}})

    commands = []

    def fake_run(cmd, cwd=None):
        _ = cwd
        commands.append(cmd)
        if "build_people_master.py" in " ".join(cmd):
            out_path = Path(cmd[cmd.index("--out") + 1])
            out_path.write_text(json.dumps({"people": [], "count": 0}, ensure_ascii=False), encoding="utf-8")
        elif "build_stellar_homepage.py" in " ".join(cmd):
            module.HOME_DATA.write_text(json.dumps({"nodes": []}, ensure_ascii=False), encoding="utf-8")
            module.HOME_DETAIL_DATA.write_text(json.dumps({"details": {}}, ensure_ascii=False), encoding="utf-8")
            (story_map_dir / "index.html").write_text("<html>index</html>", encoding="utf-8")
        elif "report_low_coverage_places.py" in " ".join(cmd):
            module.LOW_COVERAGE_JSON.write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")
            module.LOW_COVERAGE_MD.write_text("# empty\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(module, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["build_all.py", "--markdown-smoke-check", "off"])

    rc = module.main()

    assert rc == 0
    render_cmd = next(cmd for cmd in commands if "cli/generate_pure_story_map.py" in " ".join(cmd))
    assert render_cmd[render_cmd.index("--changed-mode") + 1] == "nogeocode"


def test_build_performance_baseline_summarizes_home_payload_and_profile_pages(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    home_data = story_map_dir / "stellar_home_data.json"
    home_detail_data = story_map_dir / "stellar_home_data_detail.json"
    home_data.write_text(
        json.dumps(
            {
                "nodes": [
                    {
                        "person": "李白",
                        "has_story": True,
                        "birth_year": 701,
                        "death_year": 762,
                        "birth_lat_wgs84": 30.0,
                        "birth_lng_wgs84": 120.0,
                        "aliases": ["太白"],
                        "works": ["将进酒", "蜀道难"],
                        "work_summaries": {"将进酒": {"title": "将进酒"}},
                    },
                    {
                        "person": "杜甫",
                        "has_story": False,
                        "birth_year": 712,
                        "death_year": 770,
                        "aliases": [],
                        "works": [],
                        "work_summaries": {},
                    },
                ],
                "edges": [{"a": 0, "b": 1}],
                "kg_edges": [{"a": 0, "b": 1}],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    home_detail_data.write_text(
        json.dumps({"details": {"李白": {"review": "浪漫主义诗歌高峰。"}}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (story_map_dir / "index.html").write_text("<html>index</html>", encoding="utf-8")
    (story_map_dir / "李白.html").write_text(
        '<html><script>const data = {"person":{"name":"李白"}};window.__EXPORT_DATA__ = data;</script>'
        + ("a" * 120)
        + "</html>",
        encoding="utf-8",
    )
    (story_map_dir / "杜甫.html").write_text(
        '<html><script>const data = {"person":{"name":"杜甫"}};window.__EXPORT_DATA__ = data;</script>'
        + ("b" * 80)
        + "</html>",
        encoding="utf-8",
    )
    (data_dir / "people_summary_index.json").write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (data_dir / "work_summary_index.json").write_text(json.dumps({"items": {}}, ensure_ascii=False), encoding="utf-8")
    (data_dir / "people_birth_coords_wgs84.json").write_text(json.dumps({"李白": [30.0, 120.0]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", home_data)
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", home_detail_data)
    monkeypatch.setattr(module, "BAD_PERSON_NAMES", frozenset())

    baseline = module._build_performance_baseline()

    assert baseline["homepage_payload"]["nodes"] == 2
    assert baseline["homepage_payload"]["edges"] == 1
    assert baseline["homepage_payload"]["kg_edges"] == 1
    assert baseline["homepage_payload"]["nodes_with_coords"] == 1
    assert baseline["homepage_payload"]["nodes_with_story"] == 1
    assert baseline["homepage_payload"]["total_aliases"] == 1
    assert baseline["homepage_payload"]["total_works"] == 2
    assert baseline["homepage_payload"]["total_work_summaries"] == 1
    assert baseline["homepage_payload"]["year_range"] == {"min_year": 701, "max_year": 770}
    assert baseline["files"]["stellar_home_data"]["exists"] is True
    assert baseline["files"]["stellar_home_data"]["gzip_size"] is not None
    assert baseline["files"]["stellar_home_data_detail"]["exists"] is True
    assert baseline["files"]["stellar_home_data_detail"]["gzip_size"] is not None
    assert baseline["profile_pages"][0]["person"] == "李白"


def test_build_validation_report_flags_stale_profile_template(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")
    (story_map_dir / "李白.html").write_text("<html><script>const data = {\"person\":{\"name\":\"李白\"}};window.__EXPORT_DATA__ = data;</script></html>", encoding="utf-8")
    (data_dir / "people_master.json").write_text(
        json.dumps({"people": [{"person": "李白", "has_story": True, "story_md": "storymap/examples/story/李白.md"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (story_map_dir / "stellar_home_data.json").write_text(
        json.dumps({"nodes": [{"person": "李白", "file": "李白.html", "has_story": True, "birth_lat_wgs84": 30.0, "birth_lng_wgs84": 120.0}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "people_birth_coords_wgs84.json").write_text(json.dumps({"李白": [30.0, 120.0]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", story_map_dir / "stellar_home_data.json")
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", story_map_dir / "stellar_home_data_detail.json")

    report = module._build_validation_report()

    assert report["ok"] is False
    stale_issue = next(item for item in report["errors"] if item["code"] == "story_html_template_stale")
    assert stale_issue["samples"] == ["李白"]


def test_patch_has_story_uses_publishable_story_people(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")
    (story_dir / "嫦娥.md").write_text("# 嫦娥\n", encoding="utf-8")

    master_path = data_dir / "people_master.json"
    master_path.write_text(
        json.dumps(
            {
                "people": [
                    {"person": "李白", "has_story": False, "story_md": ""},
                    {"person": "嫦娥", "has_story": True, "story_md": "storymap/examples/story/嫦娥.md"},
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    home_path = story_map_dir / "stellar_home_data.json"
    home_path.write_text(
        json.dumps(
            {
                "nodes": [
                    {"person": "李白", "has_story": False},
                    {"person": "嫦娥", "has_story": True},
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "story_person_names", lambda path: ["李白"])

    master_stat = module._patch_master_with_has_story(master_path)
    home_stat = module._patch_home_with_has_story(home_path)
    master_payload = json.loads(master_path.read_text(encoding="utf-8"))
    home_payload = json.loads(home_path.read_text(encoding="utf-8"))

    assert master_stat == {"updated": 2, "total": 2}
    assert home_stat == {"updated": 2, "total": 2}
    assert master_payload["people"] == [
        {"person": "李白", "has_story": True, "story_md": "storymap/examples/story/李白.md"},
        {"person": "嫦娥", "has_story": False, "story_md": ""},
    ]
    assert home_payload["nodes"] == [
        {"person": "李白", "has_story": True},
        {"person": "嫦娥", "has_story": False},
    ]


def test_build_validation_report_ignores_non_publishable_story_markdown(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (story_dir / "李白.md").write_text("# 李白\n", encoding="utf-8")
    (story_dir / "嫦娥.md").write_text("# 嫦娥 神话人物\n", encoding="utf-8")
    (story_map_dir / "李白.html").write_text(
        "<html><script>const data = {\"person\":{\"name\":\"李白\"},\"templateSignature\":\"ok\"};window.__EXPORT_DATA__ = data;</script></html>",
        encoding="utf-8",
    )
    (data_dir / "people_master.json").write_text(
        json.dumps({"people": [{"person": "李白", "has_story": True, "story_md": "storymap/examples/story/李白.md"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "people_master_pep.json").write_text(
        json.dumps({"people": [{"person": "李白", "has_story": True, "story_md": "storymap/examples/story/李白.md"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (story_map_dir / "stellar_home_data.json").write_text(
        json.dumps({"nodes": [{"person": "李白", "file": "李白.html", "has_story": True, "birth_lat_wgs84": 30.0, "birth_lng_wgs84": 120.0}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "people_birth_coords_wgs84.json").write_text(json.dumps({"李白": [30.0, 120.0]}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", story_map_dir / "stellar_home_data.json")
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", story_map_dir / "stellar_home_data_detail.json")
    monkeypatch.setattr(module, "story_person_names", lambda path: ["李白"])
    monkeypatch.setattr(module, "profile_template_signature", lambda: "ok")

    report = module._build_validation_report()

    assert report["ok"] is True
    samples = [sample for issue in report["errors"] + report["warnings"] for sample in issue.get("samples", [])]
    assert "嫦娥" not in samples


def test_build_validation_report_ignores_alias_redirect_stub_html(tmp_path, monkeypatch):
    module = importlib.import_module("tools.build_all")
    story_dir = tmp_path / "storymap" / "examples" / "story"
    story_map_dir = tmp_path / "artifacts" / "story_map"
    data_dir = tmp_path / "data"
    story_dir.mkdir(parents=True)
    story_map_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)

    (story_dir / "苏东坡.md").write_text("# 苏东坡\n", encoding="utf-8")
    (story_map_dir / "苏东坡.html").write_text(
        "<html><script>window.location.replace('./%E8%8B%8F%E8%BD%BC.html')</script></html>",
        encoding="utf-8",
    )
    (data_dir / "people_master.json").write_text(
        json.dumps({"people": [{"person": "苏东坡", "has_story": True, "story_md": "storymap/examples/story/苏东坡.md"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "people_master_pep.json").write_text(
        json.dumps({"people": [{"person": "苏东坡", "has_story": True, "story_md": "storymap/examples/story/苏东坡.md"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (story_map_dir / "stellar_home_data.json").write_text(
        json.dumps({"nodes": [{"person": "苏东坡", "file": "苏东坡.html", "has_story": True}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (data_dir / "people_birth_coords_wgs84.json").write_text(json.dumps({}, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(module, "STORY_DIR", story_dir)
    monkeypatch.setattr(module, "STORY_MAP_DIR", story_map_dir)
    monkeypatch.setattr(module, "DATA_DIR", data_dir)
    monkeypatch.setattr(module, "HOME_DATA", story_map_dir / "stellar_home_data.json")
    monkeypatch.setattr(module, "HOME_DETAIL_DATA", story_map_dir / "stellar_home_data_detail.json")
    monkeypatch.setattr(module, "story_person_names", lambda path: ["苏东坡"])
    monkeypatch.setattr(module, "profile_template_signature", lambda: "ok")

    report = module._build_validation_report()

    assert report["ok"] is False
    missing_html_issue = next(item for item in report["errors"] if item["code"] == "story_missing_html")
    assert missing_html_issue["samples"] == ["苏东坡"]
    assert module._existing_htmls() == set()
