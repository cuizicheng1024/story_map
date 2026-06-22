import json
import os
import sqlite3
from typing import Dict, Iterable, List, Tuple


class TaskStorageBackend:
    def __init__(self, *, db_path: str, logger: object) -> None:
        self.db_path = str(db_path or "").strip()
        self._logger = logger
        self._db = self._open_db()
        self._ensure_task_table()

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass

    def load_tasks(self) -> Dict[str, Dict[str, object]]:
        recovered: Dict[str, Dict[str, object]] = {}
        try:
            rows = self._db.execute("SELECT id, payload FROM tasks").fetchall()
        except Exception as exc:
            self._logger.warning("task_state_load_failed path=%s error=%s", self.db_path, exc)
            return recovered
        for task_id, payload_text in rows:
            try:
                payload = json.loads(str(payload_text or ""))
            except Exception:
                continue
            if isinstance(payload, dict):
                recovered[str(task_id)] = payload
        return recovered

    def query_tasks(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        status: str = "",
    ) -> Tuple[List[Dict[str, object]], int]:
        normalized_status = str(status or "").strip()
        safe_limit = max(1, min(int(limit), 200))
        safe_offset = max(0, int(offset))
        if normalized_status:
            rows = self._db.execute(
                """
                SELECT payload FROM tasks
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (normalized_status, safe_limit, safe_offset),
            ).fetchall()
            total = int(
                self._db.execute("SELECT COUNT(*) FROM tasks WHERE status = ?", (normalized_status,)).fetchone()[0]
            )
        else:
            rows = self._db.execute(
                "SELECT payload FROM tasks ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (safe_limit, safe_offset),
            ).fetchall()
            total = int(self._db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
        items: List[Dict[str, object]] = []
        for (payload_text,) in rows:
            try:
                payload = json.loads(str(payload_text or ""))
            except Exception:
                continue
            if isinstance(payload, dict):
                items.append(payload)
        return items, total

    def upsert_task(self, task: Dict[str, object]) -> None:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return
        payload_text = json.dumps(task, ensure_ascii=False)
        status = str(task.get("status") or "").strip()
        updated_at = float(task.get("updated_at") or 0)
        with self._db:
            self._db.execute(
                "REPLACE INTO tasks (id, status, updated_at, payload) VALUES (?, ?, ?, ?)",
                (task_id, status, updated_at, payload_text),
            )

    def delete_tasks(self, task_ids: Iterable[str]) -> None:
        ids = [str(task_id).strip() for task_id in task_ids if str(task_id).strip()]
        if not ids:
            return
        with self._db:
            self._db.executemany("DELETE FROM tasks WHERE id = ?", ((task_id,) for task_id in ids))

    def replace_all_tasks(self, tasks: Iterable[Dict[str, object]]) -> None:
        payloads = [
            (
                str(task.get("id") or ""),
                str(task.get("status") or "").strip(),
                float(task.get("updated_at") or 0),
                json.dumps(task, ensure_ascii=False),
            )
            for task in tasks
            if str(task.get("id") or "").strip()
        ]
        with self._db:
            self._db.execute("DELETE FROM tasks")
            self._db.executemany(
                "REPLACE INTO tasks (id, status, updated_at, payload) VALUES (?, ?, ?, ?)",
                payloads,
            )

    def vacuum(self) -> None:
        with self._db:
            self._db.commit()
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._db.execute("VACUUM")
            self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def file_sizes(self) -> Dict[str, int]:
        main_size = self._safe_getsize(self.db_path)
        wal_size = self._safe_getsize(f"{self.db_path}-wal")
        shm_size = self._safe_getsize(f"{self.db_path}-shm")
        return {
            "main_size_bytes": int(main_size),
            "wal_size_bytes": int(wal_size),
            "shm_size_bytes": int(shm_size),
            "total_size_bytes": int(main_size + wal_size + shm_size),
        }

    def _open_db(self) -> sqlite3.Connection:
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _ensure_task_table(self) -> None:
        with self._db:
            self._db.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
        columns = {
            str(row[1] or "").strip()
            for row in self._db.execute("PRAGMA table_info(tasks)").fetchall()
            if len(row) >= 2
        }
        if "status" not in columns:
            with self._db:
                self._db.execute("ALTER TABLE tasks ADD COLUMN status TEXT NOT NULL DEFAULT ''")
        with self._db:
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_updated_at
                ON tasks(updated_at)
                """
            )
            self._db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tasks_status_updated_at
                ON tasks(status, updated_at DESC)
                """
            )

    def _safe_getsize(self, path: str) -> int:
        try:
            return os.path.getsize(path) if os.path.exists(path) else 0
        except Exception:
            return 0
