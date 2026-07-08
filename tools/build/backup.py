#!/usr/bin/env python3
"""管线回滚工具 — 全量备份 + 一键恢复。

在 Editor/GeoLocator 修改文件前创建 tar.gz 备份，支持一键恢复。

用法:
  python3 tools/build/backup.py create                     # 创建备份
  python3 tools/build/backup.py restore [backup.tar.gz]    # 恢复（默认最新）
  python3 tools/build/backup.py list                       # 列出所有备份
  python3 tools/build/backup.py clean --keep 5             # 清理旧备份
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = REPO_ROOT / "tools" / "debug" / "backups"
STORY_MAP_DIR = REPO_ROOT / "artifacts" / "story_map"


def create_backup() -> Path:
    """创建全量备份并返回备份文件路径。"""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    if not STORY_MAP_DIR.exists():
        raise FileNotFoundError(f"源目录不存在: {STORY_MAP_DIR}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"storymap_{timestamp}.tar.gz"

    print(f"创建备份: {backup_path}")
    with tarfile.open(backup_path, "w:gz") as tar:
        for html_file in sorted(STORY_MAP_DIR.glob("*.html")):
            tar.add(html_file, arcname=html_file.name)

    size_mb = backup_path.stat().st_size / (1024 * 1024)
    print(f"  ✓ 备份完成 ({size_mb:.1f} MB, {_count_html()} 个文件)")
    return backup_path


def restore_backup(backup_path: Path | None = None) -> bool:
    """恢复指定备份（默认最新）。"""
    if backup_path is None:
        backups = list_backups()
        if not backups:
            print("没有可用的备份")
            return False
        backup_path = backups[0]

    if not backup_path.exists():
        print(f"备份文件不存在: {backup_path}")
        return False

    print(f"恢复备份: {backup_path.name}")
    print(f"  覆盖目录: {STORY_MAP_DIR}")

    # 恢复前先备份当前状态
    print("  保存当前状态为 .pre_restore 备份...")
    pre_restore = BACKUP_DIR / f"pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
    with tarfile.open(pre_restore, "w:gz") as tar:
        for html_file in sorted(STORY_MAP_DIR.glob("*.html")):
            tar.add(html_file, arcname=html_file.name)

    with tarfile.open(backup_path, "r:gz") as tar:
        tar.extractall(STORY_MAP_DIR)

    print(f"  ✓ 恢复完成 ({_count_html()} 个文件)")
    return True


def list_backups() -> list[Path]:
    """列出所有备份（最新在前）。"""
    if not BACKUP_DIR.exists():
        return []
    backups = sorted(
        BACKUP_DIR.glob("storymap_*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    # 排除 pre_restore 文件
    backups = [b for b in backups if "pre_restore" not in b.name]
    return backups


def clean_backups(keep: int = 5) -> int:
    """清理旧备份，保留最近 N 个。"""
    backups = list_backups()
    to_delete = backups[keep:]
    for b in to_delete:
        b.unlink()
        print(f"  删除: {b.name}")
    print(f"  保留 {min(len(backups), keep)} 个，删除 {len(to_delete)} 个")
    return len(to_delete)


def _count_html() -> int:
    """统计当前 HTML 文件数。"""
    if not STORY_MAP_DIR.exists():
        return 0
    return len(list(STORY_MAP_DIR.glob("*.html")))


def main() -> int:
    ap = argparse.ArgumentParser(description="管线回滚工具")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("create", help="创建全量备份")
    restore_p = sub.add_parser("restore", help="恢复备份")
    restore_p.add_argument("backup", nargs="?", type=Path, help="备份文件路径（默认最新）")
    sub.add_parser("list", help="列出所有备份")
    clean_p = sub.add_parser("clean", help="清理旧备份")
    clean_p.add_argument("--keep", type=int, default=5, help="保留最近 N 个（默认 5）")

    args = ap.parse_args()

    try:
        if args.command == "create":
            path = create_backup()
            print(f"\n备份路径: {path}")
        elif args.command == "restore":
            restore_backup(args.backup)
        elif args.command == "list":
            backups = list_backups()
            if not backups:
                print("(无备份)")
            for i, b in enumerate(backups):
                size_mb = b.stat().st_size / (1024 * 1024)
                print(f"  {i+1}. {b.name} ({size_mb:.1f} MB)")
        elif args.command == "clean":
            clean_backups(args.keep)
        return 0
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
