#!/usr/bin/env python3
"""build_all.py - 数据单源构建入口

职责：
  1. 重新生成 data/corpus/people_master.json（教材总索引；旧 data/people_master.json 软链兼容）
  2. 重新生成 data/corpus/people_master_pep.json（PEP 教材人物；旧根路径软链兼容）
  3. 增量重渲染 artifacts/story_map/*.html（人物页）
  4. 重新生成 data/corpus/people_birth_coords_wgs84.json（出生地经纬度；旧根路径软链兼容）
  5. 重新生成 data/corpus/people_summary_index.json（人物摘要索引；旧根路径软链兼容）
  6. 重新生成 data/corpus/work_summary_index.json（作品摘要索引；旧根路径软链兼容）
  7. 重新生成 artifacts/story_map/stellar_home_data.json + index.html

数据源：单一来源 = storymap/examples/story/*.md
幂等：默认不会触发 LLM 补缺；批量人物页渲染默认走 nogeocode 模式，专门补坐标时再显式切到 pure/cache。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from importlib import import_module
from pathlib import Path

from storymap.script.core.project_paths import (
    BAD_PERSON_NAMES,
    classify_story_markdown_authenticity,
    data_reports_output_path,
    project_root_path,
    story_artifacts_dir_path,
    story_md_dir_path,
    story_person_names,
)
from storymap.script.profile.renderer import profile_template_signature
from tools.build.pipeline import manifest as pipeline_manifest
from tools.build.pipeline import performance as pipeline_performance
from tools.build.pipeline import validation as pipeline_validation
from tools.build.pipeline.reporting import PipelineReport, StepResult

REPO_ROOT = project_root_path()
STORY_DIR = story_md_dir_path()
STORY_MAP_DIR = story_artifacts_dir_path()
DATA_DIR = REPO_ROOT / "data"
HOME_DATA = STORY_MAP_DIR / "stellar_home_data.json"
HOME_DETAIL_DATA = STORY_MAP_DIR / "stellar_home_data_detail.json"
MANIFEST_JSON = data_reports_output_path("build_manifest.json")
VALIDATION_JSON = data_reports_output_path("build_validation_report.json")
MARKDOWN_SMOKE_JSON = data_reports_output_path("markdown_smoke_report.json")
LOW_COVERAGE_JSON = data_reports_output_path("low_coverage_story_report.json")
LOW_COVERAGE_MD = data_reports_output_path("low_coverage_story_report.md")
PERF_BASELINE_JSON = data_reports_output_path("performance_baseline.json")


def _data_corpus_input_path(filename: str) -> Path:
    corpus_path = DATA_DIR / "corpus" / filename
    legacy_path = DATA_DIR / filename
    if corpus_path.exists() or not legacy_path.exists():
        return corpus_path
    return legacy_path


def _data_corpus_output_path(filename: str) -> Path:
    path = DATA_DIR / "corpus" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path = DATA_DIR / filename
    if not legacy_path.exists():
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            legacy_path.write_text("{}", encoding="utf-8")
        except OSError:
            pass
    return path


def _print_section(title: str) -> None:
    bar = "─" * 60
    print(f"\n{bar}\n  {title}\n{bar}", flush=True)


def _load_hooks() -> dict[str, dict[str, list[str]]]:
    """加载管线 Hooks 配置（从环境变量 BUILD_HOOKS 或 config 文件）。

    格式: JSON dict，key 为步骤名如 "1/10"，value 为 {"pre": [...], "post": [...]}
    每个 hook 条目为 shell 命令字符串或 "python:module.func" 格式。
    """
    hooks_raw = os.environ.get("BUILD_HOOKS", "")
    if not hooks_raw:
        config_path = REPO_ROOT / "tools" / "build" / "hooks.json"
        if config_path.exists():
            hooks_raw = config_path.read_text(encoding="utf-8")
    if not hooks_raw:
        return {}
    try:
        return json.loads(hooks_raw)
    except Exception:
        return {}


def _run_hook(step_name: str, phase: str, hooks_config: dict[str, dict[str, list[str]]]) -> None:
    """执行指定步骤的 pre/post hooks。"""
    step_hooks = hooks_config.get(step_name, {}).get(phase, [])
    if not step_hooks:
        return

    for hook in step_hooks:
        try:
            if hook.startswith("python:"):
                # Python 函数钩子: "python:module.path.func_name"
                func_path = hook[len("python:"):]
                parts = func_path.split(".")
                module_name = ".".join(parts[:-1])
                func_name = parts[-1]
                mod = import_module(module_name)
                getattr(mod, func_name)(step_name, phase)
            else:
                # Shell 命令钩子
                subprocess.run(
                    hook, shell=True, cwd=str(REPO_ROOT),
                    timeout=60, check=False,
                    env={**os.environ, "BUILD_STEP": step_name, "BUILD_PHASE": phase},
                )
        except Exception as exc:
            print(f"  ⚠ Hook [{phase} {step_name}] 失败: {exc}", flush=True)


def _run(cmd: list[str], cwd: str | None = None) -> int:
    print(f"  $ {' '.join(cmd)}", flush=True)
    return subprocess.call(cmd, cwd=cwd or str(REPO_ROOT))


def _git_changed_story_files() -> list[Path]:
    story_prefix = "storymap/examples/story/"
    changed: set[Path] = set()
    commands = [
        ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD", "--", story_prefix],
        ["git", "ls-files", "--others", "--exclude-standard", "--", story_prefix],
    ]
    for cmd in commands:
        try:
            out = subprocess.check_output(cmd, cwd=str(REPO_ROOT), text=True, stderr=subprocess.DEVNULL)
        except Exception:
            continue
        for raw in out.splitlines():
            rel = raw.strip()
            if not rel.endswith(".md"):
                continue
            p = (REPO_ROOT / rel).resolve()
            if p.exists():
                changed.add(p)
    return sorted(changed)


def _run_markdown_smoke_check(scope: str) -> int:
    scope = (scope or "off").strip().lower()
    if scope == "off":
        print("  · 已跳过 Markdown 冒烟校验", flush=True)
        return 0
    files: list[Path]
    if scope == "all":
        files = _story_files()
    else:
        files = _git_changed_story_files()
    if not files:
        print("  · 未发现需要校验的 Markdown 变更", flush=True)
        return 0
    cmd = [
        sys.executable,
        "tools/reports/validate_story_markdown.py",
        "--report-json",
        str(MARKDOWN_SMOKE_JSON),
        "--files",
        *[str(p.relative_to(REPO_ROOT)) for p in files],
    ]
    return _run(cmd)


def _story_files() -> list[Path]:
    if not STORY_DIR.exists():
        return []
    return sorted(STORY_DIR.glob("*.md"))


def _story_people() -> list[str]:
    return sorted(set(story_person_names(STORY_DIR)))


def _existing_htmls() -> set[str]:
    if not STORY_MAP_DIR.exists():
        return set()
    return {p.stem for p in STORY_MAP_DIR.glob("*.html") if _is_export_profile_html(p)}


def _is_export_profile_html(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    if path.name == "index.html":
        return False
    stem = path.stem.strip()
    if not stem or "__pure__" in stem or stem in BAD_PERSON_NAMES:
        return False
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    return "window.__EXPORT_DATA__" in text


def _canonical_html_people() -> list[str]:
    out: list[str] = []
    if not STORY_MAP_DIR.exists():
        return out
    for p in STORY_MAP_DIR.glob("*.html"):
        if not _is_export_profile_html(p):
            continue
        out.append(p.stem.strip())
    return sorted(set(out))


def _rejected_story_people() -> set[str]:
    rejected: set[str] = set()
    for path in _story_files():
        name = path.stem.strip()
        if not name or name in BAD_PERSON_NAMES:
            continue
        accepted, _ = classify_story_markdown_authenticity(path)
        if not accepted:
            rejected.add(name)
    return rejected


def _cleanup_non_publishable_artifacts() -> dict:
    removed: list[str] = []
    if not STORY_MAP_DIR.exists():
        return {"removed": 0, "samples": []}
    rejected_people = _rejected_story_people()
    for path in sorted(STORY_MAP_DIR.iterdir()):
        if not path.is_file():
            continue
        if path.name == "index.html":
            continue
        stem = path.stem.strip()
        suffix = path.suffix.lower()
        should_delete = False
        if "__pure__" in stem and suffix == ".html":
            should_delete = True
        elif stem in BAD_PERSON_NAMES:
            should_delete = True
        elif stem in rejected_people and suffix in {".html", ".csv"}:
            should_delete = True
        if not should_delete:
            continue
        try:
            path.unlink()
            removed.append(path.name)
        except Exception:
            continue
    # 同时清理 portraits 目录中被 BAD_PERSON_NAMES 污染的文件
    portraits_dir = STORY_MAP_DIR / "portraits"
    if portraits_dir.exists() and portraits_dir.is_dir():
        for path in sorted(portraits_dir.iterdir()):
            if not path.is_file():
                continue
            stem = str(path.stem or "").strip()
            # 文件名格式: <人物名>-<hash>，提取人物名部分
            person_part = stem.rsplit("-", 1)[0] if "-" in stem else stem
            if person_part in BAD_PERSON_NAMES or person_part in rejected_people:
                try:
                    path.unlink()
                    removed.append(f"portraits/{path.name}")
                except Exception:
                    continue
    return {"removed": len(removed), "samples": removed[:20]}


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha1_file(path: Path) -> str:
    return pipeline_performance.sha1_file(path)


def _file_meta(path: Path) -> dict:
    return pipeline_performance.file_meta(path, REPO_ROOT)


def _gzip_size_bytes(path: Path) -> int | None:
    return pipeline_performance.gzip_size_bytes(path)


def _safe_int(value: object) -> int | None:
    return pipeline_performance.safe_int(value)


def _home_payload_metrics(path: Path) -> dict:
    return pipeline_performance.home_payload_metrics(path)


def _sample_profile_pages(limit: int = 3) -> list[dict]:
    return pipeline_performance.sample_profile_pages(STORY_MAP_DIR, REPO_ROOT, _is_export_profile_html, limit=limit)


def _baseline_file_metrics(path: Path) -> dict:
    return pipeline_performance.baseline_file_metrics(path, REPO_ROOT)


def _build_performance_baseline() -> dict:
    return pipeline_performance.build_performance_baseline(
        repo_root=REPO_ROOT,
        story_map_dir=STORY_MAP_DIR,
        home_data=HOME_DATA,
        home_detail_data=HOME_DETAIL_DATA,
        data_corpus_input_path=_data_corpus_input_path,
        is_export_profile_html=_is_export_profile_html,
    )


def _print_performance_summary(baseline: dict) -> None:
    pipeline_performance.print_performance_summary(baseline)


def _load_people_index(path: Path, key: str) -> dict[str, dict]:
    return pipeline_manifest.load_people_index(path, key)


def _load_coords_index(path: Path) -> dict[str, list[float]]:
    return pipeline_manifest.load_coords_index(path)


def _has_home_coords(node: dict) -> bool:
    return pipeline_performance.has_home_coords(node)


def _extract_html_template_signature(path: Path) -> str:
    return pipeline_validation.extract_html_template_signature(path)


def _issue(code: str, items: list[str], level: str, message: str, limit: int = 20) -> dict | None:
    return pipeline_validation.issue(code, items, level, message, limit=limit)


def _build_manifest() -> dict:
    return pipeline_manifest.build_manifest(
        repo_root=REPO_ROOT,
        story_dir=STORY_DIR,
        story_map_dir=STORY_MAP_DIR,
        home_data=HOME_DATA,
        markdown_smoke_json=MARKDOWN_SMOKE_JSON,
        low_coverage_json=LOW_COVERAGE_JSON,
        low_coverage_md=LOW_COVERAGE_MD,
        perf_baseline_json=PERF_BASELINE_JSON,
        story_people=_story_people,
        canonical_html_people=_canonical_html_people,
        data_corpus_input_path=_data_corpus_input_path,
    )


def _build_validation_report() -> dict:
    return pipeline_validation.build_validation_report(
        story_dir=STORY_DIR,
        story_map_dir=STORY_MAP_DIR,
        home_data=HOME_DATA,
        story_people=_story_people,
        canonical_html_people=_canonical_html_people,
        data_corpus_input_path=_data_corpus_input_path,
        profile_template_signature=profile_template_signature,
    )


def _patch_master_with_has_story(master_fp: Path) -> dict:
    """按可发布 Markdown 口径强制刷新 has_story 与 story_md 字段。"""
    obj = json.loads(master_fp.read_text(encoding="utf-8"))
    people = obj.get("people", [])
    if not isinstance(people, list):
        return {"updated": 0, "total": 0}
    publishable_people = set(_story_people())
    updated = 0
    for p in people:
        name = str(p.get("person", "")).strip()
        if not name:
            continue
        has_story = name in publishable_people
        was = bool(p.get("has_story"))
        if was != has_story:
            updated += 1
        p["has_story"] = has_story
        p["story_md"] = f"storymap/examples/story/{name}.md" if has_story else ""
    obj["count"] = len(people)
    obj["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    master_fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated": updated, "total": len(people)}


def _patch_home_with_has_story(home_fp: Path) -> dict:
    """给首页节点补 has_story 字段，源于可发布 Markdown 口径。"""
    obj = json.loads(home_fp.read_text(encoding="utf-8"))
    nodes = obj.get("nodes", [])
    if not isinstance(nodes, list):
        return {"updated": 0, "total": 0}
    publishable_people = set(_story_people())
    updated = 0
    for n in nodes:
        name = str(n.get("person", "")).strip()
        if not name:
            continue
        has_story = name in publishable_people
        was = n.get("has_story")
        if was != has_story:
            updated += 1
        n["has_story"] = has_story
    obj["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    home_fp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"updated": updated, "total": len(nodes)}


# ═══════════════════════════════════════════════════════════════
#  管线韧性：软依赖 + 结果汇总
# ═══════════════════════════════════════════════════════════════

def _sync_game_artifacts() -> int:
    """同步游戏产物（软依赖，委托给 sync_games 模块）。"""
    from tools.build.sync_games import sync_game_artifacts as _sync
    return _sync()


def _sync_knowledge_audit() -> int:
    """知识审计 + 自动修复 + 坐标补全 + 记忆写入（软依赖）— 使用 AssemblerAgent 五 Agent 管线。"""
    try:
        # 修改前创建备份
        from tools.build.backup import create_backup
        backup_path = create_backup()
        print(f"  ✓ 备份已创建: {backup_path.name}", flush=True)

        from tools.build.agents.assembler import AssemblerAgent

        assembler = AssemblerAgent(verbose=True, parallel=True)
        report = assembler.run()
        print(f"  ✓ 管线完成: {report.message}", flush=True)

        if report.is_failed():
            print(f"  ⚠ 部分 Agent 失败，详见上方日志", flush=True)
            return 1

        summary = report.details.get("summary", {})
        for agent_name, agent_info in summary.items():
            if isinstance(agent_info, dict):
                dur = agent_info.get("duration", 0)
                msg = agent_info.get("message", "")
                status = agent_info.get("status", "?")
                print(f"    · {agent_name} [{status}] ({dur:.1f}s): {msg}", flush=True)

        return 0
    except Exception as exc:
        print(f"  ⚠ 知识审计跳过 ({exc})", flush=True)
        return 1


def _detect_data_drift() -> int:
    """检测未经审计的新文件（对比 scan_cache.json）。"""
    try:
        cache_path = REPO_ROOT / "tools" / "debug" / "scan_cache.json"
        html_dir = REPO_ROOT / "artifacts" / "story_map"

        cached_files: set[str] = set()
        if cache_path.exists():
            cached_files = set(json.loads(cache_path.read_text(encoding="utf-8")).keys())

        current_files = {f.stem for f in html_dir.glob("*.html")}

        new_files = current_files - cached_files
        removed_files = cached_files - current_files

        if new_files:
            print(f"  ⚠ 漂移检测: {len(new_files)} 个新文件未经审计", flush=True)
            for name in sorted(new_files)[:10]:
                print(f"    · {name}", flush=True)
            if len(new_files) > 10:
                print(f"    ... 等 {len(new_files)} 个", flush=True)
            return 1

        if removed_files:
            print(f"  ℹ {len(removed_files)} 个文件已从缓存移除", flush=True)

        print(f"  ✓ 漂移检测通过: {len(current_files)} 个文件全部已审计", flush=True)
        return 0
    except Exception as exc:
        print(f"  ⚠ 漂移检测跳过 ({exc})", flush=True)
        return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="数据单源构建入口（幂等）")
    ap.add_argument("--skip-master", action="store_true")
    ap.add_argument("--skip-pep", action="store_true")
    ap.add_argument("--skip-html", action="store_true")
    ap.add_argument("--skip-home", action="store_true")
    ap.add_argument("--validate", action="store_true", help="兼容保留；当前默认已在校验错误时返回非 0")
    ap.add_argument("--validate-only", action="store_true", help="只生成 manifest 与校验报告，不执行重建")
    ap.add_argument("--allow-validation-errors", action="store_true", help="即使校验报告存在错误也返回 0")
    ap.add_argument(
        "--markdown-smoke-check",
        choices=["off", "changed", "all"],
        default="changed",
        help="构建前执行 Markdown 冒烟校验：changed=仅校验 git 变更文件，all=全量校验，off=关闭",
    )
    ap.add_argument("--refresh-geocode", action="store_true",
                    help="兼容保留；默认批量渲染已走 pure 模式，会在缺失坐标时补齐地理编码")
    ap.add_argument("--fill-missing-md", action="store_true",
                    help="对 master 里没有 .md 的人物尝试 LLM 生成（需要 API key）")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()

    t0 = time.time()
    story_files = _story_files()
    html_files = _existing_htmls()
    print(f"[init] .md 源文件: {len(story_files)} 个, 已渲染 .html: {len(html_files)} 个")

    report = PipelineReport()
    hooks = _load_hooks()

    def _step(name: str, label: str, fn, hard: bool = False) -> bool:
        """执行一个管线步骤。hard=True 时失败会立即中止。返回是否继续。"""
        _run_hook(name, "pre", hooks)
        _print_section(f"{name} {label}")
        t_start = time.time()
        try:
            rc = fn()
            dur = time.time() - t_start
            if isinstance(rc, int) and rc != 0:
                sr = StepResult(name, label, "failed", f"退出码 {rc}", dur)
                report.add(sr)
                if hard:
                    report.hard_failures.append(name)
                    print(f"  ⛔ 硬依赖失败，管线中止", flush=True)
                    return False
                _run_hook(name, "post", hooks)
                return True
            sr = StepResult(name, label, "ok", duration=dur)
            report.add(sr)
            _run_hook(name, "post", hooks)
            return True
        except Exception as exc:
            dur = time.time() - t_start
            msg = str(exc)[:120]
            sr = StepResult(name, label, "failed", msg, dur)
            report.add(sr)
            if hard:
                report.hard_failures.append(name)
                print(f"  ⛔ 硬依赖失败，管线中止", flush=True)
                return False
            print(f"  ⚠ 软依赖失败，继续执行 ({msg})", flush=True)
            _run_hook(name, "post", hooks)
            return True

    def _parallel_steps(steps: list[tuple[str, str, callable]]) -> None:
        """并发执行一组软依赖步骤。"""
        if not steps:
            return
        if len(steps) == 1:
            _step(steps[0][0], steps[0][1], steps[0][2])
            return

        labels = [l for _, l, _ in steps]
        print(f"  ⚡ 并行组 [{', '.join(labels)}] 启动...", flush=True)
        t_group = time.time()

        with ThreadPoolExecutor(max_workers=len(steps)) as executor:
            futures = {
                executor.submit(fn): (name, label)
                for name, label, fn in steps
            }
            for future in as_completed(futures):
                name, label = futures[future]
                t_start = time.time()
                try:
                    rc = future.result()
                    dur = time.time() - t_start
                    if isinstance(rc, int) and rc != 0:
                        report.add(StepResult(name, label, "failed", f"退出码 {rc}", dur))
                    else:
                        report.add(StepResult(name, label, "ok", duration=dur))
                except Exception as exc:
                    dur = time.time() - t_start
                    msg = str(exc)[:120]
                    report.add(StepResult(name, label, "failed", msg, dur))

        print(f"  ⚡ 并行组完成 ({time.time() - t_group:.1f}s)", flush=True)

    # ── 0. Markdown 冒烟校验（硬依赖） ────────────────────────
    if not _step("0/10", "markdown smoke check",
                 lambda: _run_markdown_smoke_check(args.markdown_smoke_check),
                 hard=True):
        report.print_summary()
        return 2

    if args.validate_only:
        manifest = _build_manifest()
        report2 = _build_validation_report()
        baseline = _build_performance_baseline()
        _write_json(MANIFEST_JSON, manifest)
        _write_json(VALIDATION_JSON, report2)
        _write_json(PERF_BASELINE_JSON, baseline)
        print(f"[validate-only] manifest: {MANIFEST_JSON}")
        print(f"[validate-only] report:   {VALIDATION_JSON}")
        print(f"[validate-only] perf:     {PERF_BASELINE_JSON}")
        print(f"[validate-only] ok={report2['ok']} errors={report2['summary']['error_count']} warnings={report2['summary']['warning_count']}")
        _print_performance_summary(baseline)
        return 0 if report2["ok"] else 2

    # ── 1. people_master.json（硬依赖） ─────────────────────────
    if not args.skip_master:
        ok = _step("1/10", "rebuild people_master.json", lambda: _run([
            sys.executable, "tools/build_people_master.py",
            "--scope", "all",
            "--out", str(_data_corpus_output_path("people_master.json")),
            "--concurrency", str(args.concurrency),
        ]), hard=True)
        if not ok:
            report.print_summary()
            return 2
        master_fp = _data_corpus_input_path("people_master.json")
        stat = _patch_master_with_has_story(master_fp)
        print(f"  ✓ has_story 字段按可发布 Markdown 强制刷新: {stat['updated']} 处变更, {stat['total']} 人", flush=True)

    # ── 并行组 A: 2 + 5 + 6（均依赖步骤 1 people_master，互不依赖） ──
    parallel_a: list[tuple[str, str, callable]] = []
    if not args.skip_pep:
        def _step2():
            rc = _run([
                sys.executable, "tools/build_people_master.py",
                "--scope", "pep",
                "--out", str(_data_corpus_output_path("people_master_pep.json")),
                "--concurrency", str(args.concurrency),
            ])
            pep_fp = _data_corpus_input_path("people_master_pep.json")
            if pep_fp.exists():
                stat = _patch_master_with_has_story(pep_fp)
                print(f"  ✓ pep has_story 字段按可发布 Markdown 强制刷新: {stat['updated']} 处变更, {stat['total']} 人", flush=True)
            return rc
        parallel_a.append(("2/10", "rebuild people_master_pep.json", _step2))
    if not args.skip_home:
        parallel_a.append(("5/10", "rebuild people_summary_index.json",
                           lambda: _run([sys.executable, "tools/build_people_summary_index.py"])))
        parallel_a.append(("6/10", "rebuild work_summary_index.json",
                           lambda: _run([sys.executable, "tools/build_work_summary_index.py"])))
    _parallel_steps(parallel_a)

    # ── 3. 增量重渲染人物页（硬依赖） ────────────────────────────
    if not args.skip_html:
        ok = _step("3/10", "render changed artifacts/story_map/*.html", lambda: _run([
            sys.executable, "cli/generate_pure_story_map.py",
            "--render-changed",
            "--changed-mode", "nogeocode",
            "--changed-limit", "0",
        ]), hard=True)
        if not ok:
            report.print_summary()
            return 2
        cleanup = _cleanup_non_publishable_artifacts()
        print(f"  ✓ 已清理不可发布/临时产物: {cleanup['removed']} 个", flush=True)
        if cleanup["samples"]:
            print(f"    样例: {', '.join(cleanup['samples'])}", flush=True)

    # ── 并行组 B: 4 + 8 + 9（均依赖步骤 3 HTML 渲染，互不依赖） ──
    _parallel_steps([
        ("4/10", "sync birth_coords_wgs84.json",
         lambda: (print("  · 坐标由 homepage/main.py 统一生成，跳过") if not args.refresh_geocode else None) or 0),
        ("8/10", "sync game artifacts", lambda: _sync_game_artifacts()),
        ("9/10", "knowledge audit + auto-fix + coords", lambda: _sync_knowledge_audit()),
    ])

    # ── 7. 首页数据（硬依赖，依赖步骤 3） ──────────────────────────
    if not args.skip_home:
        ok = _step("7/10", "rebuild stellar_home_data.json + index.html", lambda: _run([
            sys.executable, "tools/build/homepage/main.py",
            "--story-map-dir", str(STORY_MAP_DIR),
            "--story-md-dir", str(STORY_DIR),
        ]), hard=True)
        if not ok:
            report.print_summary()
            return 2
        if HOME_DATA.exists():
            stat = _patch_home_with_has_story(HOME_DATA)
            print(f"  ✓ home has_story 字段按可发布 Markdown 强制刷新: {stat['updated']} 处变更, {stat['total']} 节点", flush=True)

    # ── 收尾统计 ────────────────────────────────────────────────
    # 漂移检测（软依赖）
    _step("D", "data drift detection", lambda: _detect_data_drift())
    elapsed = time.time() - t0
    story_files = _story_files()
    html_files = _existing_htmls()
    print(f"\n[done] .md={len(story_files)} .html={len(html_files)}  耗时 {elapsed:.1f}s")
    if not story_files and not html_files:
        print("  ⚠ 警告：未找到 .md 源文件。请确认 storymap/examples/story/ 目录非空。")

    manifest = _build_manifest()
    validation = _build_validation_report()
    baseline = _build_performance_baseline()
    _write_json(MANIFEST_JSON, manifest)
    _write_json(VALIDATION_JSON, validation)
    _write_json(PERF_BASELINE_JSON, baseline)

    _print_section("coverage report")
    rc = _run(
        [
            sys.executable,
            "tools/report_low_coverage_places.py",
            "--story-dir",
            str(STORY_DIR),
            "--out-json",
            str(LOW_COVERAGE_JSON),
            "--out-md",
            str(LOW_COVERAGE_MD),
        ]
    )
    if rc != 0:
        print(f"  ✗ report_low_coverage_places.py 退出码 {rc}", flush=True)

    _write_json(MANIFEST_JSON, _build_manifest())
    print(f"[manifest] {MANIFEST_JSON}")
    print(f"[validate] {VALIDATION_JSON}  ok={validation['ok']} errors={validation['summary']['error_count']} warnings={validation['summary']['warning_count']}")
    print(f"[perf] {PERF_BASELINE_JSON}")
    _print_performance_summary(baseline)

    # ── 管线汇总 ────────────────────────────────────────────
    report.print_summary()

    # 硬失败 → 非 0；仅软失败 + validation 无硬错误 → 0
    if report.hard_failures:
        return 2
    if (not validation["ok"]) and (not args.allow_validation_errors):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
