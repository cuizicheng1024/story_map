import importlib
import json


def test_build_report_confirms_latest_pages_deploy():
    module = importlib.import_module("tools.check_pages_deploy")

    def _fake_fetch(url: str):
        if "api.github.com" in url:
            return {
                "workflow_runs": [
                    {
                        "id": 27249749717,
                        "head_sha": "abc123",
                        "display_title": "track built story map artifacts",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.com/example/actions/runs/27249749717",
                        "created_at": "2026-06-10T02:48:47Z",
                        "updated_at": "2026-06-10T02:49:37Z",
                    }
                ]
            }
        return {
            "generated_at": "2026-06-10 02:49:19",
            "source_commit": "abc123",
            "pages_run_id": 27249749717,
            "pages_run_attempt": 1,
        }

    report = module.build_report(
        owner="cuizicheng1024",
        repo="storymap",
        workflow_file="deploy-pages.yml",
        site_json_url="https://cuizicheng1024.github.io/storymap/stellar_home_data.json",
        expected_sha="abc123",
        fetch_json=_fake_fetch,
        cache_bust_stamp=1,
    )

    assert report["ok"] is True
    assert report["workflow"]["run_id"] == 27249749717
    assert report["live_site"]["source_commit"] == "abc123"
    assert report["live_site"]["pages_run_id"] == 27249749717
    assert all(item["ok"] for item in report["checks"])


def test_with_cache_bust_preserves_existing_query_parameters():
    module = importlib.import_module("tools.check_pages_deploy")

    url = module._with_cache_bust("https://example.com/data.json?a=1", stamp=42)

    assert "a=1" in url
    assert "_ts=42" in url


def test_main_reports_error_as_json(monkeypatch, capsys):
    module = importlib.import_module("tools.check_pages_deploy")

    monkeypatch.setattr(module, "_git_head", lambda: "abc123")
    monkeypatch.setattr(module, "build_report", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("rate limit exceeded")))
    monkeypatch.setattr(module.sys, "argv", ["check_pages_deploy.py"])

    exit_code = module.main()
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["expected_sha"] == "abc123"
    assert "rate limit exceeded" in payload["error"]
