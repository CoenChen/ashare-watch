"""零依赖 HTTP 服务 + 后台定时刷新。

用标准库 ``http.server`` 而不是 Web 框架：用户拿到项目后不需要 pip install
任何东西，装了 Python 就能跑。这个服务的职责很窄（返回一份 JSON + 几个静态
文件），引入框架的依赖成本大于收益。

刷新节奏按 A 股交易时段自动切换：

* 盘中（9:30–11:30、13:00–15:00）：每 ``refresh_seconds`` 秒（默认 60）
* 其余时间：每 ``idle_seconds`` 秒（默认 15 分钟）
"""

from __future__ import annotations

import json
import logging
import mimetypes
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ashare_watch.collector import Collector
from ashare_watch.config import Settings, get_settings
from ashare_watch.models import Snapshot
from ashare_watch.render import export_snapshot
from ashare_watch.store import SnapshotStore

LOGGER = logging.getLogger("ashare_watch.server")

STATIC_DIR = Path(__file__).parent / "static"
POLL_HINT_SECONDS = 10


class DashboardState:
    """服务进程内的共享状态：最新快照 + 调度信息。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        self.snapshot: Snapshot | None = None
        self.last_refresh_at = 0.0
        self.refreshing = False
        self.refresh_count = 0
        self.last_error = ""

    @property
    def interval(self) -> int:
        if self.snapshot and self.snapshot.market.is_open:
            return max(self.settings.min_refresh_seconds, self.settings.refresh_seconds)
        return max(60, self.settings.idle_seconds)

    def next_refresh_in(self) -> int:
        if self.last_refresh_at <= 0:
            return 0
        return max(0, int(self.interval - (time.monotonic() - self.last_refresh_at)))

    def set_snapshot(self, snapshot: Snapshot) -> None:
        with self.lock:
            self.snapshot = snapshot
            self.last_refresh_at = time.monotonic()
            self.refresh_count += 1
            self.last_error = ""

    def get_snapshot(self) -> Snapshot | None:
        with self.lock:
            return self.snapshot

    def meta(self) -> dict:
        with self.lock:
            return {
                "next_refresh_in": self.next_refresh_in(),
                "refresh_seconds": self.settings.refresh_seconds,
                "idle_seconds": self.settings.idle_seconds,
                "interval": self.interval,
                "poll_interval": POLL_HINT_SECONDS,
                "refreshing": self.refreshing,
                "refresh_count": self.refresh_count,
                "last_error": self.last_error,
            }


class RefreshWorker(threading.Thread):
    def __init__(self, collector: Collector, state: DashboardState) -> None:
        super().__init__(name="refresh-worker", daemon=True)
        self.collector = collector
        self.state = state
        self._wake = threading.Event()
        self._stop = threading.Event()

    def trigger(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def run(self) -> None:
        # 先做一次"快速刷新"（指数 + 自选股 + 板块），再补全市场。
        # 全市场要翻 56 页，先让页面有东西可看，再在后台补齐榜单和统计。
        self._refresh(include_universe=False)
        self._refresh(include_universe=True)
        while not self._stop.is_set():
            self._wake.wait(timeout=self.state.interval)
            self._wake.clear()
            if self._stop.is_set():
                break
            if self.state.next_refresh_in() > 0 and not self._wake.is_set():
                continue
            self._refresh(include_universe=True)

    def _refresh(self, *, include_universe: bool = True) -> None:
        if self.state.refreshing:
            return
        self.state.refreshing = True
        try:
            snapshot = self.collector.refresh(include_universe=include_universe)
            self.state.set_snapshot(snapshot)
            LOGGER.info(
                "刷新完成（第 %d 次，%s）：%s  耗时 %.1fs",
                self.state.refresh_count,
                "全量" if include_universe else "快速",
                snapshot.fetched_at,
                snapshot.generated_ms / 1000,
            )
        except Exception as error:  # noqa: BLE001 - 后台线程不能让异常终结服务
            with self.state.lock:
                self.state.last_error = f"{type(error).__name__}: {error}"
            LOGGER.exception("刷新失败")
        finally:
            self.state.refreshing = False


class Handler(BaseHTTPRequestHandler):
    server_version = "AShareWatch/1.0"
    protocol_version = "HTTP/1.1"

    state: DashboardState
    collector: Collector
    worker: RefreshWorker

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        LOGGER.debug("%s - %s", self.address_string(), fmt % args)

    def _send(self, body: bytes, status: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, payload: object, status: int = 200) -> None:
        self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), status)

    def _send_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        guessed = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(path.read_bytes(), 200, guessed.split(";")[0])

    def _safe_static(self, name: str) -> Path | None:
        target = (STATIC_DIR / name).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())):
            return None
        return target

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._send_file(STATIC_DIR / "index.html", "text/html")
            return
        if path.startswith("/static/"):
            target = self._safe_static(path[len("/static/") :])
            if target is None:
                self._send_json({"error": "forbidden"}, 403)
                return
            self._send_file(target)
            return
        if path == "/api/dashboard":
            snapshot = self.state.get_snapshot()
            self._send_json(
                {"snapshot": snapshot.to_dict() if snapshot else None, "meta": self.state.meta()}
            )
            return
        if path == "/api/runs":
            self._send_json({"runs": self.collector.store.recent_runs(20)})
            return
        if path == "/api/search-index":
            # 搜索索引单独成接口，不塞进快照：它有两百多 KB，
            # 而快照每 15 秒被序列化一次、还要存 500 份进 SQLite。
            # 前端只在加载时和每 5 分钟取一次，成本可以忽略。
            self._send_json({"rows": self.collector.search_index()})
            return
        if path == "/api/health":
            self._send_json(
                {
                    "status": "ok",
                    "refresh_count": self.state.refresh_count,
                    "last_error": self.state.last_error,
                    "store": self.collector.store.count(),
                    "client": self.collector.client.stats,
                }
            )
            return
        self._send_json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/refresh":
            try:
                snapshot = self.collector.refresh()
                self.state.set_snapshot(snapshot)
                self._send_json({"ok": True, "fetched_at": snapshot.fetched_at})
            except Exception as error:  # noqa: BLE001
                self._send_json({"ok": False, "error": str(error)}, 500)
            return
        if path == "/api/export":
            snapshot = self.state.get_snapshot()
            if snapshot is None:
                self._send_json({"ok": False, "error": "还没有可导出的数据"}, 400)
                return
            target = export_snapshot(snapshot.to_dict(), self.state.settings)
            self._send_json({"ok": True, "path": str(target)})
            return
        self._send_json({"error": "not found"}, 404)


def create_server(
    settings: Settings | None = None, *, start_worker: bool = True
) -> tuple[ThreadingHTTPServer, DashboardState, RefreshWorker, Collector]:
    settings = settings or get_settings()
    settings.ensure_dirs()

    store = SnapshotStore(settings.db_path)
    collector = Collector(settings=settings, store=store)
    state = DashboardState(settings)

    # 先用上次的快照把页面撑起来，避免首屏空白
    cached = store.latest_snapshot()
    if cached:
        fields = {k: v for k, v in cached.items() if k in Snapshot.__dataclass_fields__}
        try:
            state.snapshot = Snapshot(**fields)
        except TypeError:
            LOGGER.warning("缓存快照结构不兼容，已忽略")

    worker = RefreshWorker(collector, state)
    Handler.state = state
    Handler.collector = collector
    Handler.worker = worker

    httpd = ThreadingHTTPServer((settings.host, settings.port), Handler)
    httpd.daemon_threads = True
    if start_worker:
        worker.start()
    return httpd, state, worker, collector


def serve(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    httpd, _state, worker, _collector = create_server(settings)
    url = f"http://{settings.host}:{settings.port}"
    print(f"A 股实时行情已启动：{url}")
    print(f"  刷新节奏：盘中 {settings.refresh_seconds} 秒 / 其他时段 {settings.idle_seconds} 秒")
    print(f"  数据文件：{settings.db_path}")
    print("  按 Ctrl+C 停止")

    if settings.open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        worker.stop()
        httpd.shutdown()
        httpd.server_close()
