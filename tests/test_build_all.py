import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
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
    monkeypatch.setattr(module, "MANIFEST_JSON", data_dir / "build_manifest.json")
    monkeypatch.setattr(module, "VALIDATION_JSON", data_dir / "build_validation_report.json")
    monkeypatch.setattr(module, "MARKDOWN_SMOKE_JSON", data_dir / "markdown_smoke_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_JSON", data_dir / "low_coverage_story_report.json")
    monkeypatch.setattr(module, "LOW_COVERAGE_MD", data_dir / "low_coverage_story_report.md")
    monkeypatch.setattr(module, "BAD_PERSON_NAMES", frozenset())
    monkeypatch.setattr(module, "_run_markdown_smoke_check", lambda _scope: 0)

    def _fake_run(cmd, cwd=None):
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
                (story_map_dir / f"{person}.html").write_text(f"<html>{person}</html>", encoding="utf-8")
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
    assert (story_map_dir / "stellar_home_data.json").exists()
    assert (story_map_dir / "index.html").exists()
    assert (story_map_dir / "李白.html").exists()
    assert (story_map_dir / "王昭君.html").exists()


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
    monkeypatch.setattr(module, "MANIFEST_JSON", data_dir / "build_manifest.json")
    monkeypatch.setattr(module, "VALIDATION_JSON", data_dir / "build_validation_report.json")
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
    monkeypatch.setattr(module, "MANIFEST_JSON", data_dir / "build_manifest.json")
    monkeypatch.setattr(module, "VALIDATION_JSON", data_dir / "build_validation_report.json")
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
