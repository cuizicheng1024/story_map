from __future__ import annotations

import argparse
import re
import time
from typing import Callable, Dict, List, Optional


_TASK_LIKE_TOKENS = (
    "为什么",
    "为何",
    "如何",
    "怎么",
    "请",
    "帮我",
    "比较",
    "对比",
    "分析",
    "总结",
    "解释",
    "给我",
    "什么",
    "哪里",
    "哪儿",
    "谁",
    "轨迹",
    "足迹",
    "证据",
    "活动",
)


def _looks_like_person_name(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) > 12:
        return False
    if re.search(r"[?？!！。:：；;（）()\[\]{}<>/\\]", cleaned):
        return False
    return not any(token in cleaned for token in _TASK_LIKE_TOKENS)


def _is_usable_result(result: Dict[str, object]) -> bool:
    if bool(result.get("ok")):
        return True
    return str(result.get("status") or "").strip() == "degraded"


def _summarize_quality_issues(issues: List[str]) -> str:
    cleaned = [str(item).strip() for item in list(issues or []) if str(item).strip()]
    if not cleaned:
        return ""
    return "；".join(cleaned[:3])


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="生成人物生平 Markdown，并导出可交互地图 HTML"
    )
    parser.add_argument("-p", "--person", help="历史人物姓名或一句包含人物的句子", required=False)
    parser.add_argument("--serve", action="store_true", help="启动 HTTP 服务")
    parser.add_argument("--port", type=int, default=8765, help="HTTP 服务端口")
    return parser


def resolve_targets_from_text(
    *,
    client: object,
    text: str,
    extract_historical_figures: Callable[[object, str], List[str]],
    fallback_to_input: bool,
) -> List[str]:
    targets = extract_historical_figures(client, text)
    if targets:
        return targets
    if fallback_to_input:
        fallback = str(text or "").strip()
        if _looks_like_person_name(fallback):
            return [fallback]
    return []


def run_interactive(
    *,
    create_client: Callable[[], object],
    validate_input_text: Callable[[object], Optional[str]],
    resolve_targets: Callable[[object, str, bool], List[str]],
    generate_historical_markdown: Callable[[object, str], str],
    enrich_markdown_for_map: Callable[[str], str],
    validate_data_quality: Callable[[str], List[str]],
    print_quality_report: Callable[[str], None],
    save_markdown: Callable[[str, str], str],
    parse_places: Callable[[str], List[Dict[str, str]]],
    parse_events: Callable[[str], List[Dict[str, str]]],
    build_points: Callable[..., List[Dict[str, object]]],
    render_html: Callable[[str, List[Dict[str, object]], str], str],
    render_amap_html: Callable[[str, List[Dict[str, object]], str], str],
    save_html: Callable[[str, str], str],
    format_seconds: Callable[[float], str],
    logger: object,
) -> None:
    client = create_client()
    while True:
        try:
            text = input("请输入人物或一句包含人物的句子（q 退出）：").strip()
        except EOFError:
            break
        if not text:
            continue
        err = validate_input_text(text)
        if err:
            print(err)
            continue
        if text.lower() in {"q", "quit", "exit"}:
            print("已退出。")
            break
        targets = resolve_targets(client, text, False)
        if not targets:
            print("未识别到历史人物")
            continue
        print(f"识别到人物数量：{len(targets)}")
        stats = {"markdown": 0, "html": 0, "failed": 0}
        for person in targets:
            print(f"正在生成 {person} 生平文档，可能需要一些时间...")
            t0 = time.perf_counter()
            t_step = time.perf_counter()
            md = generate_historical_markdown(client, person)
            t_md = time.perf_counter() - t_step
            if not md:
                print(f"未取得：{person}")
                stats["failed"] += 1
                continue
            print("正在进行地点地理编码，可能需要一些时间...")
            t_step = time.perf_counter()
            md = enrich_markdown_for_map(md)
            t_geo = time.perf_counter() - t_step
            quality_issues = validate_data_quality(md)
            print_quality_report(md)
            saved = save_markdown(person, md)
            t_step = time.perf_counter()
            render_error = ""
            try:
                places = parse_places(md)
                events = parse_events(md)
                pts = build_points(places, events)
                html = render_html(person, pts, md)
            except Exception as exc:
                render_error = str(exc).strip() or "地图渲染失败"
                logger.warning("render_failed person=%s error=%s", person, exc)
                html = render_amap_html(person, [], "")
            t_render = time.perf_counter() - t_step
            out = save_html(person, html)
            if render_error or quality_issues:
                summary = render_error or _summarize_quality_issues(quality_issues) or "人物页存在待修正问题"
                print(f"已生成（降级）：{saved}")
                print(f"提示：{summary}")
            else:
                print(f"已生成：{saved}")
            print(out)
            total = time.perf_counter() - t0
            print(
                f"耗时：生平生成 {format_seconds(t_md)}，地理编码 {format_seconds(t_geo)}，"
                f"地图渲染 {format_seconds(t_render)}，总计 {format_seconds(total)}"
            )
            stats["markdown"] += 1
            stats["html"] += 1
        print(
            f"本次完成：人物 {len(targets)}，文档 {stats['markdown']}，地图 {stats['html']}，失败 {stats['failed']}"
        )


def run_person_generation(
    *,
    person_text: str,
    create_client: Callable[[], object],
    validate_input_text: Callable[[object], Optional[str]],
    resolve_targets: Callable[[object, str, bool], List[str]],
    generate_for_person: Callable[[object, str], Dict[str, object]],
) -> None:
    err = validate_input_text(person_text)
    if err:
        print(err)
        return
    client = create_client()
    targets = resolve_targets(client, person_text, True)
    if not targets:
        print("未识别到人物")
        return
    stats = {"markdown": 0, "html": 0, "failed": 0}
    for person in targets:
        print(f"正在生成 {person} 生平文档，可能需要一些时间...")
        result = generate_for_person(client, person)
        if not _is_usable_result(result):
            print(f"未取得：{person}")
            stats["failed"] += 1
            continue
        if str(result.get("status") or "").strip() == "degraded":
            print(f"已生成（降级）：{person}，地图使用回退结果")
        print(f"已生成：{result.get('markdown_path')}")
        print(result.get("html_path"))
        duration = result.get("duration") or {}
        print(
            "耗时：生平生成 {markdown}，地理编码 {geocode}，地图渲染 {render}，总计 {total}".format(
                markdown=duration.get("markdown", ""),
                geocode=duration.get("geocode", ""),
                render=duration.get("render", ""),
                total=duration.get("total", ""),
            )
        )
        stats["markdown"] += 1
        stats["html"] += 1
    print(
        f"运行完成：人物 {len(targets)}，文档 {stats['markdown']}，地图 {stats['html']}，失败 {stats['failed']}"
    )
