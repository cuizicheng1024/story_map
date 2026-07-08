"""地理定位 Agent — 古地名 → 现代城市 → 高德 API / 离线字典 → 坐标回填。

策略：
  1. 古地名 → 现代城市名映射表
  2. 高德地图 Web 服务 API 地理编码（优先）
  3. 离线坐标字典降级（API 不可用时）
  4. 占位值（不详/待补充/存疑）自动移除
  5. 空 locations 数组特殊补全（苏颂/张三丰/莫扎特/韩信）

幂等：仅处理 lat=None 的条目，可安全重复执行。
境外地址自动降级走离线字典。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from storymap.script.map.offline_geo_lookup import (
    EMPTY_LOCATIONS_FALLBACK,
    UNRESOLVABLE_PERSON_PLACES,
    load_ancient_mappings,
    load_city_coords,
)
from tools.build.agents.base import AgentReport, BaseAgent
from tools.build.agents._shared import parse_embedded_json

UNRESOLVABLE = UNRESOLVABLE_PERSON_PLACES


class GeoLocatorAgent(BaseAgent):
    """地理定位 Agent — 古地名坐标自动补全。"""

    name = "geolocator"
    label = "地理定位 Agent"
    description = "古地名 → 现代城市映射 → 高德 API + 离线字典双模式坐标补全"
    max_retries = 2
    retry_delay = 2.0

    def __init__(
        self,
        html_dir: Path | None = None,
        cache_path: Path | None = None,
        verbose: bool = True,
        dry_run: bool = False,
        cache_ttl_days: int = 7,
        force_refresh: bool = False,
    ):
        super().__init__(verbose=verbose)
        repo_root = Path(__file__).resolve().parents[3]
        self.html_dir = html_dir or (repo_root / "artifacts" / "story_map")
        self.cache_path = cache_path or (repo_root / "tools" / "debug" / "geo_cache.json")
        self.dry_run = dry_run
        self.cache_ttl_days = cache_ttl_days
        self.force_refresh = force_refresh
        self._amap_key: str = ""
        self._cache: dict[str, tuple[float, float]] = {}
        self._ancient_mappings: dict[tuple[str, str], str] = {}
        self._city_coords: dict[str, tuple[float, float]] = {}

    # ── API Key 加载 ──

    def _load_amap_key(self) -> str:
        """从 .env 加载高德 Web 服务 Key。"""
        env_path = Path(__file__).resolve().parents[3] / ".env"
        if not env_path.exists():
            self._log("未找到 .env 文件，将仅使用离线字典", "warn")
            return ""

        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("AMAP_WEBSERVICE_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key and key not in ("", "your_amap_webservice_key"):
                    return key
            elif line.startswith("AMAP_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key
        return ""

    # ── 缓存管理 ──

    def _load_cache(self) -> dict[str, tuple[float, float]]:
        """加载地理编码缓存。支持 TTL 过期 + 强制刷新。"""
        if self.force_refresh:
            self._log("强制刷新，跳过缓存加载", "warn")
            return {}

        if not self.cache_path.exists():
            return {}

        # TTL 过期检查
        cache_age = time.time() - self.cache_path.stat().st_mtime
        if cache_age > self.cache_ttl_days * 86400:
            self._log(f"缓存已过期 ({cache_age / 86400:.0f} 天)，跳过加载", "warn")
            return {}

        data = self._safe_read_json(self.cache_path)
        if isinstance(data, dict):
            entries = {k: (float(v[0]), float(v[1])) for k, v in data.items() if isinstance(v, list) and len(v) == 2}
            self._log(f"加载缓存: {len(entries)} 条 ({(cache_age / 86400):.1f} 天前)")
            return entries
        return {}

    def _save_cache(self) -> None:
        """保存地理编码缓存（带时间戳）。"""
        serializable = {k: [v[0], v[1]] for k, v in self._cache.items()}
        self._safe_write_json(self.cache_path, serializable)
        self._log(f"缓存已保存: {len(self._cache)} 条")

    # ── 高德 API 地理编码 ──

    def _geocode_amap(self, address: str) -> tuple[float, float] | None:
        """通过高德 API 获取坐标，自动缓存。"""
        if address in self._cache:
            return self._cache[address]

        if not self._amap_key:
            return None

        params = urllib.parse.urlencode({
            "key": self._amap_key,
            "address": address,
            "output": "JSON",
        })
        url = f"https://restapi.amap.com/v3/geocode/geo?{params}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            self._log(f"高德 API 网络错误: {address} → {e}", "warn")
            return None
        except json.JSONDecodeError as e:
            self._log(f"高德 API 响应解析失败: {e}", "warn")
            return None
        except Exception as e:
            self._log(f"高德 API 请求异常: {address} → {e}", "warn")
            return None

        if result.get("status") != "1":
            info = result.get("info", "unknown")
            self._log(f"高德 API 返回错误 [{info}]: {address}", "warn")
            return None

        geocodes = result.get("geocodes", [])
        if not geocodes:
            self._log(f"高德未找到坐标: {address}", "warn")
            return None

        location = geocodes[0].get("location", "")
        try:
            lng_str, lat_str = location.split(",")
            lat, lng = float(lat_str), float(lng_str)
        except (ValueError, AttributeError):
            self._log(f"高德坐标解析失败: {address} → {location}", "warn")
            return None

        # 校验坐标合理性
        if abs(lat) >= 90 or abs(lng) >= 180:
            self._log(f"高德返回越界坐标: {address} ({lat}, {lng})", "warn")
            return None

        self._cache[address] = (lat, lng)
        self._log(f"高德 API ✓: {address} → ({lat:.4f}, {lng:.4f})")
        return (lat, lng)

    # ── 坐标解析（主逻辑） ──

    def _resolve_coords(self, loc_name: str, modern: str) -> dict[str, Any] | None:
        """解析坐标：高德 API → 离线字典 → None，返回 source/confidence 元数据。"""
        alias_chain = [loc_name]
        if modern != loc_name:
            alias_chain.append(modern)

        coords = self._geocode_amap(modern)
        if coords is not None:
            confidence = 0.95 if modern == loc_name else 0.88
            return {"lat": coords[0], "lng": coords[1], "source": "amap", "confidence": confidence, "alias_chain": alias_chain}

        coords = self._city_coords.get(modern)
        if coords is not None:
            self._log(f"离线字典降级: {modern} → ({coords[0]:.4f}, {coords[1]:.4f})")
            confidence = 0.8 if modern == loc_name else 0.78
            return {"lat": coords[0], "lng": coords[1], "source": "city_coords.json", "confidence": confidence, "alias_chain": alias_chain}

        self._log(f"无法定位: {modern}", "warn")
        return None

    # ── 单文件修复 ──

    def _fix_one(self, filepath: Path) -> dict[str, Any]:
        """修复单个 HTML 文件的坐标。返回变更摘要。"""
        name = filepath.stem
        result = {"person": name, "fixed": 0, "removed": 0, "failed": 0, "skipped": 0}

        try:
            html = self._safe_read(filepath)
            if html is None:
                result["failed"] += 1
                self._log(f"读取失败: {name}.html", "error")
                return result
        except Exception as e:
            result["failed"] += 1
            self._log(f"读取异常: {name}.html → {e}", "error")
            return result

        data, old_json = parse_embedded_json(html)
        if data is None:
            return result

        locations = data.get("locations", [])

        # 空数组特殊补全
        if not locations and name in EMPTY_LOCATIONS_FALLBACK:
            data["locations"] = EMPTY_LOCATIONS_FALLBACK[name]
            if not self.dry_run:
                new_json = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
                new_html = html.replace(old_json, new_json, 1)
                self._safe_write(filepath, new_html)
            count = len(EMPTY_LOCATIONS_FALLBACK[name])
            result["fixed"] += count
            self._log(f"补全空 locations 数组: {name} ({count} 个地点)", "ok")
            return result

        if not locations:
            return result

        changed = False
        has_removals = False

        for loc in locations:
            loc_name = loc.get("name", "")
            lat = loc.get("lat")
            lng = loc.get("lng") or loc.get("lon")

            # 幂等：跳过已有坐标的条目
            if lat is not None and lng is not None:
                continue

            key = (name, loc_name)

            # 移除占位值
            if key in UNRESOLVABLE:
                loc["_remove"] = True
                has_removals = True
                result["removed"] += 1
                self._log(f"移除占位值: {name} '{loc_name}'")
                continue

            # 古地名 → 现代城市
            modern = self._ancient_mappings.get(key)
            if modern is None:
                result["skipped"] += 1
                continue

            # 获取坐标
            resolved = self._resolve_coords(loc_name, modern)
            if resolved is None:
                result["failed"] += 1
                continue

            loc["lat"] = resolved["lat"]
            loc["lng"] = resolved["lng"]
            loc["modernName"] = modern
            loc["geocodeSource"] = resolved["source"]
            loc["geocodeConfidence"] = resolved["confidence"]
            loc["geocodeAliasChain"] = resolved["alias_chain"]
            loc["geocodeResolvedBy"] = "GeoLocatorAgent"
            changed = True
            result["fixed"] += 1

        # 回写文件
        if changed or has_removals:
            data["locations"] = [loc for loc in locations if not loc.pop("_remove", False)]
            if not self.dry_run:
                new_json = json.dumps(data, ensure_ascii=False, separators=(",", ": "))
                new_html = html.replace(old_json, new_json, 1)
                # 事务安全：先写临时文件，再原子替换
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".html",
                    dir=filepath.parent, delete=False,
                )
                try:
                    tmp.write(new_html)
                    tmp.close()
                    Path(tmp.name).replace(filepath)
                except Exception:
                    Path(tmp.name).unlink(missing_ok=True)
                    raise

        return result

    # ── 输入校验 ──

    def _pre_run(self) -> None:
        super()._pre_run()
        if not self.html_dir.exists():
            raise FileNotFoundError(f"HTML 目录不存在: {self.html_dir}")

        self._amap_key = self._load_amap_key()
        if self._amap_key:
            masked = f"{self._amap_key[:6]}...{self._amap_key[-4:]}"
            self._log(f"高德 API Key: {masked}")
        else:
            self._log("未配置高德 API Key，仅使用离线字典", "warn")

        self._cache = self._load_cache()
        self._log(f"地理编码缓存: {len(self._cache)} 条")

        # 加载外部数据文件
        self._ancient_mappings = load_ancient_mappings(required=True)
        self._city_coords = load_city_coords(required=True)
        self._log(f"古地名映射: {len(self._ancient_mappings)} 条, 离线坐标: {len(self._city_coords)} 个")

    def _post_run(self, report: AgentReport) -> AgentReport:
        """保存缓存。"""
        self._save_cache()
        self._log(f"缓存已保存: {len(self._cache)} 条")
        return super()._post_run(report)

    # ── 主执行 ──

    def _execute(self, **kwargs) -> AgentReport:
        # 确定需要处理的文件列表
        if "names" in kwargs:
            person_names = kwargs["names"]
        else:
            # 预过滤：只扫描映射表中出现过的人物 + 空数组补全人物
            mapped_people = {k[0] for k in self._ancient_mappings}
            mapped_people.update(EMPTY_LOCATIONS_FALLBACK.keys())
            mapped_people.update(k[0] for k in UNRESOLVABLE)
            all_files = sorted(
                p.stem for p in self.html_dir.glob("*.html")
                if p.is_file()
            )
            if mapped_people:
                person_names = [n for n in all_files if n in mapped_people]
                self._log(f"预过滤: {len(person_names)}/{len(all_files)} 文件在映射表中")
            else:
                person_names = all_files

        total_fixed = 0
        total_removed = 0
        total_failed = 0
        total_skipped = 0
        processed = 0

        max_workers = kwargs.get("max_workers", min(8, max(len(person_names), 1)))

        def _process(name: str) -> dict:
            filepath = self.html_dir / f"{name}.html"
            if not filepath.exists():
                self._log(f"文件不存在: {name}.html", "warn")
                return {"fixed": 0, "removed": 0, "failed": 0, "skipped": 0}
            return self._fix_one(filepath)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(_process, name): name for name in person_names}
            for future in as_completed(futures):
                result = future.result()
                total_fixed += result["fixed"]
                total_removed += result["removed"]
                total_failed += result["failed"]
                total_skipped += result["skipped"]
                processed += 1

        if self.dry_run:
            self._log("DRY-RUN 模式，未实际写入文件", "warn")

        return AgentReport(
            agent_name=self.name,
            status="ok",
            message=f"修复 {total_fixed} 处, 移除占位 {total_removed} 处, 失败 {total_failed}, 跳过 {total_skipped}",
            details={
                "fixed": total_fixed,
                "removed": total_removed,
                "failed": total_failed,
                "skipped": total_skipped,
                "processed": processed,
                "cache_size": len(self._cache),
                "api_available": bool(self._amap_key),
                "dry_run": self.dry_run,
            },
            warnings=(
                [f"高德 API 不可用，仅使用离线字典"]
                if not self._amap_key
                else []
            ),
        )


# ── CLI ──
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="地理定位 Agent — 古地名坐标补全")
    ap.add_argument("--dir", type=Path, default=None, help="HTML 目录")
    ap.add_argument("--dry-run", action="store_true", help="预览模式")
    ap.add_argument("--force-refresh", action="store_true", help="强制刷新缓存")
    ap.add_argument("--cache-ttl", type=int, default=7, help="缓存 TTL（天）")
    args = ap.parse_args()
    agent = GeoLocatorAgent(
        html_dir=args.dir, dry_run=args.dry_run,
        force_refresh=args.force_refresh, cache_ttl_days=args.cache_ttl,
        verbose=True,
    )
    report = agent.run()
    print(f"\n{report.message}")
