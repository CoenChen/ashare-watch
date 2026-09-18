"""SQLite 持久化：快照历史 + 采集日志。

存快照的作用有三个：服务重启后能立刻用上次数据渲染（不用等第一次抓取）、
前端可以展示数据更新时间线、以及保留一份可回溯的行情存档。

采集日志用来回答"今天为什么没更新"——不用猜，直接看每轮的耗时和失败数。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at  TEXT NOT NULL,
    saved_at    TEXT NOT NULL,
    status      TEXT,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_fetched ON snapshots(fetched_at DESC);

CREATE TABLE IF NOT EXISTS collection_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT NOT NULL,
    status        TEXT NOT NULL,
    duration_ms   REAL,
    requests      INTEGER DEFAULT 0,
    failures      INTEGER DEFAULT 0,
    market_status TEXT,
    message       TEXT
);
"""

MAX_SNAPSHOTS = 500


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _age_seconds(stamp: str) -> float | None:
    """``saved_at`` 距今多少秒。解析不了就返回 None（当作太旧处理）。"""
    try:
        saved = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if saved.tzinfo is None:
        saved = saved.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - saved.astimezone(timezone.utc)).total_seconds()


class SnapshotStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.executescript(SCHEMA)
            self._connection.commit()

    def save_snapshot(self, snapshot: dict) -> int:
        payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
        status = (snapshot.get("market") or {}).get("status", "")
        with self._lock:
            cursor = self._connection.execute(
                "INSERT INTO snapshots (fetched_at, saved_at, status, payload) VALUES (?,?,?,?)",
                (snapshot.get("fetched_at", ""), _now(), status, payload),
            )
            self._connection.commit()
            self._prune_locked()
            return int(cursor.lastrowid or 0)

    def _prune_locked(self) -> None:
        self._connection.execute(
            "DELETE FROM snapshots WHERE id NOT IN "
            "(SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)",
            (MAX_SNAPSHOTS,),
        )
        self._connection.commit()

    def latest_snapshot(self) -> dict | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def recent_snapshots(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, fetched_at, saved_at, status FROM snapshots ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_complete_snapshot(
        self, *, min_universe: int = 1000, max_age_seconds: float | None = None
    ) -> dict | None:
        """最近一份「全市场数据完整」的快照。

        抓取偶尔会**成功但只拿到一部分**：接口临时限流时，全市场那 56 页会
        大面积失败，快照照样会存下来，只是榜单、市场宽度、涨跌停统计全是空的。

        对导出/兜底这种场景来说，一份「稍旧但完整」的快照远比「最新但空掉一半」
        有用——后者打开就是一个残缺页面，看的人会以为项目坏了。

        ``max_age_seconds`` 用来限定"足够新"：本地看板正在跑的时候，store 里
        通常已经有一份几分钟前刚抓好的完整数据，导出直接拿来用就行，
        再翻一遍 56 页纯属白烧请求。
        """
        with self._lock:
            rows = self._connection.execute(
                "SELECT payload, saved_at FROM snapshots ORDER BY id DESC LIMIT 60"
            ).fetchall()
        for row in rows:
            if max_age_seconds is not None:
                age = _age_seconds(row["saved_at"])
                if age is None or age > max_age_seconds:
                    break  # 按时间倒序取，后面的只会更旧
            payload = json.loads(row["payload"])
            if (payload.get("coverage") or {}).get("universe", 0) >= min_universe:
                return payload
        return None

    def log_run(
        self,
        *,
        started_at: str,
        finished_at: str,
        status: str,
        duration_ms: float,
        requests: int,
        failures: int,
        market_status: str = "",
        message: str = "",
    ) -> None:
        with self._lock:
            self._connection.execute(
                "INSERT INTO collection_log (started_at, finished_at, status, duration_ms,"
                " requests, failures, market_status, message) VALUES (?,?,?,?,?,?,?,?)",
                (
                    started_at,
                    finished_at,
                    status,
                    round(duration_ms, 1),
                    requests,
                    failures,
                    market_status,
                    message[:500],
                ),
            )
            self._connection.commit()

    def recent_runs(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM collection_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def count(self) -> dict[str, int]:
        with self._lock:
            snapshots = self._connection.execute(
                "SELECT COUNT(*) AS n FROM snapshots"
            ).fetchone()["n"]
            runs = self._connection.execute(
                "SELECT COUNT(*) AS n FROM collection_log"
            ).fetchone()["n"]
        return {"snapshots": int(snapshots), "runs": int(runs)}

    def close(self) -> None:
        with self._lock:
            self._connection.close()
