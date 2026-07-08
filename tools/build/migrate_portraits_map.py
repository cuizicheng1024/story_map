#!/usr/bin/env python3
"""将 portraits_map.json 从旧格式 (名→文件名) 迁移到新格式 (名→{file, source, source_label})。

旧格式：
  {"孔子": "孔子-4a4306bb1cf7.jpg"}

新格式：
  {"孔子": {"file": "孔子-4a4306bb1cf7.jpg", "source": "real", "source_label": "传世画像"}}

source 取值：
  - "real"     : 真实历史人物的传世画像/照片
  - "ai"       : AI 生成的艺术风格肖像
  - "wiki"     : 来自 Wikimedia Commons 的画像/照片
  - "unknown"  : 来源未知（默认值）

以后新增肖像时需要明确标记来源。
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PORTRAITS_MAP_PATH = REPO_ROOT / "data" / "corpus" / "portraits_map.json"


def main():
    if not PORTRAITS_MAP_PATH.exists():
        print(f"file not found: {PORTRAITS_MAP_PATH}", file=sys.stderr)
        return 1

    original = json.loads(PORTRAITS_MAP_PATH.read_text(encoding="utf-8"))

    # 检查是否已迁移（第一个值为 dict 则跳过）
    for v in original.values():
        if isinstance(v, dict):
            print("portraits_map.json 已经是新格式，跳过迁移")
            return 0
        break

    migrated = {}
    for name, value in original.items():
        if isinstance(value, dict):
            migrated[name] = value
        else:
            # 旧格式：纯字符串文件名 → 标记为 unknown
            migrated[name] = {
                "file": value,
                "source": "unknown",
                "source_label": "",
            }

    # 备份原文件
    backup = PORTRAITS_MAP_PATH.with_suffix(".json.bak")
    backup.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"备份已保存: {backup}")

    # 写入新格式
    PORTRAITS_MAP_PATH.write_text(
        json.dumps(migrated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"迁移完成: {len(migrated)} 条肖像记录")
    print(f"  - 全部标记为 source='unknown'")
    print(f"  - 如需标记 AI 生成/真实图像，请手动编辑 source 和 source_label 字段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
