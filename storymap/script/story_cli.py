from __future__ import annotations

import argparse
import time
from typing import Callable, Dict, List, Optional


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
        if fallback:
            return [fallback]
    return []


def run_interactive(
    *,
    create_client: Callable[[], object],
    validate_input_text: Callable[[object], Optional[str]],
    resolve_targets: Callable[[object, str, bool], List[str]],
    generate_historical_markdown: Callable[[object, str], str],
    normalize_markdown_tables: Callable[[str], str],
    compute_total_distance_km: Callable[[str], object],
    insert_distance_intro: Callable[[str, float], str],
    append_coords_section: Callable[[str], str],
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
            md = normalize_markdown_tables(md)
            km = compute_total_distance_km(md)
            if isinstance(km, float):
                md = insert_distance_intro(md, km)
            print("正在进行地点地理编码，可能需要一些时间...")
            t_step = time.perf_counter()
            md = append_coords_section(md)
            t_geo = time.perf_counter() - t_step
            print_quality_report(md)
            saved = save_markdown(person, md)
            print(f"已生成：{saved}")
            t_step = time.perf_counter()
            try:
                places = parse_places(md)
                events = parse_events(md)
                pts = build_points(places, events)
                html = render_html(person, pts, md)
            except Exception as exc:
                logger.warning("render_failed person=%s error=%s", person, exc)
                html = render_amap_html(person, [], "")
            t_render = time.perf_counter() - t_step
            out = save_html(person, html)
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
        if not result.get("ok"):
            print(f"未取得：{person}")
            stats["failed"] += 1
            continue
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
