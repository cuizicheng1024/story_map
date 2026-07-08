"""安全 JSON 持久化基类。

提供幂等的原子写入（tmp + replace）、stale-tmp 恢复、以及统一的读写锁机制。
所有 JSON 文件存储类可继承此类以避免 pid-based tmp 文件的残留冲突。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Dict

_LOGGER = logging.getLogger("story_map.persistence")


class SafeJSONStore:
    """线程安全的 JSON 文件持久化基类。

    - 使用 tmp + atomic replace 避免写入中断导致文件损坏。
    - 启动时自动清理残留的 stale *.tmp 文件。
    - 提供统一的 _load / _save 方法，子类只需关心数据结构。
    """

    def __init__(self, target_path: Path) -> None:
        self._path = Path(target_path)
        self._lock = threading.RLock()
        self._recover_stale_tmp_files()

    def _recover_stale_tmp_files(self) -> None:
        """清理残留的临时文件（上次崩溃未完成 rename）。"""
        parent = self._path.parent
        if not parent.exists():
            return
        stem = self._path.name
        suffix = self._path.suffix
        for entry in parent.iterdir():
            if not entry.is_file():
                continue
            if entry.name.startswith(stem) and f"{suffix}.tmp" in entry.name:
                try:
                    # 如果目标文件不存在，尝试用 tmp 恢复
                    if not self._path.exists() and entry.stat().st_size > 0:
                        _LOGGER.debug("从残留 tmp 文件恢复: %s", entry)
                        entry.rename(self._path)
                    else:
                        entry.unlink()
                except OSError as exc:
                    _LOGGER.debug("清理残留 tmp 文件失败: %s: %s", entry, exc)

    def _load(self) -> Dict:
        with self._lock:
            if not self._path.exists():
                return {}
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                _LOGGER.warning("JSON 文件读取失败: %s: %s", self._path, exc)
                return {}
        return payload if isinstance(payload, dict) else {}

    def _save(self, payload: Dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(f"{self._path.name}.tmp.{os.getpid()}")
        try:
            with self._lock:
                tmp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                tmp_path.replace(self._path)
        except OSError:
            # 如果 replace 失败，清理 tmp 文件并重试一次
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
                tmp_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                tmp_path.replace(self._path)
            except OSError as exc:
                _LOGGER.error("JSON 持久化写入失败: %s: %s", self._path, exc)
                raise


__all__ = ["SafeJSONStore"]
