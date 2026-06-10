from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_head() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def _with_cache_bust(url: str, *, stamp: Optional[int] = None) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["_ts"] = str(int(stamp if stamp is not None else time.time()))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _fetch_json(url: str, *, timeout: float = 20.0) -> Dict[str, Any]:
    token = str(os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or "").strip()
    headers = {
        "Accept": "application/vnd.github+json, application/json",
        "User-Agent": "storymap-pages-check",
    }
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(
        url,
        headers=headers,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        if exc.code == 403 and "rate limit exceeded" in body.lower():
            raise RuntimeError("GitHub API rate limit exceeded; set GITHUB_TOKEN or GH_TOKEN and retry") from exc
        raise RuntimeError(f"HTTP {exc.code}: {body.strip() or exc.reason}") from exc


def _latest_workflow_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    runs = payload.get("workflow_runs")
    if isinstance(runs, list):
        for item in runs:
            if isinstance(item, dict):
                return item
    return {}


def build_report(
    *,
    owner: str,
    repo: str,
    workflow_file: str,
    site_json_url: str,
    expected_sha: str = "",
    fetch_json: Optional[Callable[[str], Dict[str, Any]]] = None,
    cache_bust_stamp: Optional[int] = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    fetch = fetch_json or (lambda url: _fetch_json(url, timeout=timeout))
    workflow_url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow_file}/runs?per_page=20"
    workflow_payload = fetch(workflow_url)
    latest_run = _latest_workflow_run(workflow_payload)

    live_url = _with_cache_bust(site_json_url, stamp=cache_bust_stamp)
    live_payload = fetch(live_url) if site_json_url else {}

    run_id = latest_run.get("id")
    run_sha = str(latest_run.get("head_sha") or "").strip()
    run_status = str(latest_run.get("status") or "").strip()
    run_conclusion = str(latest_run.get("conclusion") or "").strip()
    live_commit = str(live_payload.get("source_commit") or "").strip()
    live_run_id = live_payload.get("pages_run_id")

    checks = [
        {
            "name": "workflow_completed_successfully",
            "ok": run_status == "completed" and run_conclusion == "success",
            "actual": {"status": run_status, "conclusion": run_conclusion},
        }
    ]

    ok = checks[0]["ok"]
    if expected_sha:
        matches_run = run_sha == expected_sha
        checks.append(
            {
                "name": "workflow_matches_expected_sha",
                "ok": matches_run,
                "expected": expected_sha,
                "actual": run_sha,
            }
        )
        ok = ok and matches_run

        matches_live_commit = live_commit == expected_sha
        checks.append(
            {
                "name": "live_site_matches_expected_sha",
                "ok": matches_live_commit,
                "expected": expected_sha,
                "actual": live_commit,
            }
        )
        ok = ok and matches_live_commit

    if run_id is not None:
        matches_live_run = str(live_run_id or "").strip() == str(run_id)
        checks.append(
            {
                "name": "live_site_matches_workflow_run",
                "ok": matches_live_run,
                "expected": str(run_id),
                "actual": str(live_run_id or "").strip(),
            }
        )
        ok = ok and matches_live_run

    return {
        "ok": bool(ok),
        "expected_sha": expected_sha,
        "workflow": {
            "file": workflow_file,
            "api_url": workflow_url,
            "run_id": run_id,
            "head_sha": run_sha,
            "display_title": str(latest_run.get("display_title") or ""),
            "status": run_status,
            "conclusion": run_conclusion,
            "html_url": str(latest_run.get("html_url") or ""),
            "created_at": str(latest_run.get("created_at") or ""),
            "updated_at": str(latest_run.get("updated_at") or ""),
        },
        "live_site": {
            "url": live_url,
            "generated_at": str(live_payload.get("generated_at") or ""),
            "source_commit": live_commit,
            "pages_run_id": live_run_id,
            "pages_run_attempt": live_payload.get("pages_run_attempt"),
        },
        "checks": checks,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="核验 GitHub Pages 是否已切到最新提交")
    parser.add_argument("--owner", default="cuizicheng1024", help="GitHub 仓库 owner")
    parser.add_argument("--repo", default="storymap", help="GitHub 仓库名")
    parser.add_argument("--workflow-file", default="deploy-pages.yml", help="工作流文件名")
    parser.add_argument(
        "--site-json-url",
        default="https://cuizicheng1024.github.io/storymap/stellar_home_data.json",
        help="用于核验线上 Pages 的 JSON 地址",
    )
    parser.add_argument("--expected-sha", default="", help="期望已上线的 commit SHA，默认取本地 HEAD")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次请求超时时间（秒）")
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    expected_sha = str(args.expected_sha or "").strip() or _git_head()
    try:
        report = build_report(
            owner=str(args.owner),
            repo=str(args.repo),
            workflow_file=str(args.workflow_file),
            site_json_url=str(args.site_json_url),
            expected_sha=expected_sha,
            timeout=float(args.timeout),
        )
    except Exception as exc:
        report = {
            "ok": False,
            "expected_sha": expected_sha,
            "error": str(exc),
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
