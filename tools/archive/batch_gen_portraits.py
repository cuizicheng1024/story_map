"""批量生成缺失人物AI肖像（并发3 worker，自动跳过涉政敏感人物）

调用 portrait_service 的接口逐个人物生成，自动缓存到 artifacts/story_map/portraits/
"""
import json
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storymap" / "script"))
sys.path.insert(0, str(ROOT))

import storymap.script.map.portrait_service as ps

MAX_WORKERS = 3
MIN_INTERVAL_SEC = 12  # 3 workers × 12s ≈ 15 req/min, 避免 429


def get_missing():
    with open(ROOT / "data/corpus/people_summary_index.json") as f:
        psi = json.load(f)
    items = psi.get("items", {})

    # Exclude people without enough info
    skip = {
        # 已删除人物
        "张玉兴", "曹鎏", "曹京平", "余书芬", "李剑波", "徐滨",
        "刘青山", "张子善",
        # 当代敏感政治人物（MiniMax 内容过滤）
        "习近平", "邓小平", "毛泽东", "周恩来", "朱德", "刘少奇",
        "江泽民", "胡锦涛", "温家宝", "李克强",
        # 其他可能触发过滤的
        "华国锋", "林彪", "康生", "陈伯达",
        # API 确认涉政敏感（input new_sensitive）
        "叶剑英", "塔布曼", "希特勒", "张思德", "斯大林",
        "曾联松", "李红勃", "杨得志", "杨成武", "杨树朋",
        "杨靖宇", "汉斯·希伯", "焦裕禄", "班禅额尔德尼·确吉坚赞",
        "罗盛教", "聂荣臻",
    }

    missing = []
    for name, info in sorted(items.items()):
        if name in skip:
            continue
        if ps.has_cached_portrait(name):
            continue

        intro = info.get("intro", "")
        identities = info.get("identities", "")
        title = info.get("title", "")
        status = info.get("status", "")
        era = info.get("era", "")

        dynasty = era[:2] if era else ""

        req = ps.PortraitRequest(
            name=name,
            dynasty=dynasty,
            title=title or identities[:40],
            short_bio=intro[:120] or status[:120],
            style="ink_wash",
            aspect_ratio="1:1",
        )
        missing.append(req)

    return missing


_rate_lock = threading.Lock()
_next_allowed_time = 0.0
_success_count = 0
_fail_count = 0
_sensitive_count = 0
_count_lock = threading.Lock()
_t0 = 0.0
_total = 0


def _wait_rate_limit():
    global _next_allowed_time
    with _rate_lock:
        now = time.time()
        wait = _next_allowed_time - now
        if wait > 0:
            time.sleep(wait)
        _next_allowed_time = time.time() + MIN_INTERVAL_SEC


def generate_one(req: ps.PortraitRequest) -> str:
    """返回 "ok" / "sensitive" / "fail" """
    global _success_count, _fail_count, _sensitive_count
    try:
        _wait_rate_limit()
        prompt = ps._build_prompt(req)
        blobs = ps._call_image_api(req, prompt, n=1)
        if not blobs:
            with _count_lock:
                _fail_count += 1
            return "fail"
        blob = blobs[0]
        ext = ps._sniff_extension(blob)
        path = ps.portrait_base_path(req.name).with_suffix(ext)
        path.write_bytes(blob)
        with _count_lock:
            _success_count += 1
        return "ok"
    except Exception as e:
        err = str(e)[:120]
        with _count_lock:
            if "new_sensitive" in err:
                _sensitive_count += 1
                return "sensitive"
            _fail_count += 1
        print(f"  [{req.name}] FAILED: {err}", flush=True)
        return "fail"


def main():
    global _t0, _total
    tasks = get_missing()
    _total = len(tasks)
    # 初始预估：速率限制器是全局瓶颈，实际吞吐 ≈ 间隔秒/个
    est = _total * MIN_INTERVAL_SEC
    print(f"需生成: {_total} 个头像")
    print(f"并发: {MAX_WORKERS} workers, 间隔: {MIN_INTERVAL_SEC}s")
    print(f"预估: ~{est/60:.0f} 分钟（按实际 API 耗时动态修正）")
    print()

    _t0 = time.time()
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_map = {executor.submit(generate_one, req): req for req in tasks}
        for future in as_completed(future_map):
            req = future_map[future]
            result = future.result()
            completed += 1
            elapsed = time.time() - _t0
            # 用实际均速估算剩余时间
            if completed > 0:
                eta = elapsed / completed * (_total - completed)
            else:
                eta = 0

            suffix = ""
            if result == "sensitive":
                suffix = " (涉政跳过)"
            elif result == "fail":
                suffix = " (失败)"

            pct = completed * 100 // _total
            print(f"[{completed}/{_total} {pct}%] {req.name}{suffix}  "
                  f"| 成功:{_success_count} 失败:{_fail_count} 跳过:{_sensitive_count}  "
                  f"| 均速{elapsed/completed:.0f}s/个 剩余~{eta/60:.0f}min", flush=True)

    elapsed = time.time() - _t0
    print(f"\n完成: {_success_count} 成功 / {_fail_count} 失败 / {_sensitive_count} 涉政跳过, 耗时 {elapsed/60:.0f}min")

    if _sensitive_count > 0:
        print("\n提示: 有涉政敏感人物，可加入 skip 列表避免下次重复尝试")

    return 0


if __name__ == "__main__":
    sys.exit(main())
