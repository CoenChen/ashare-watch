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
import re
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ashare_watch.collector import Collector
from ashare_watch.config import Settings, get_settings
from ashare_watch.models import Snapshot, snapshot_from_dict
from ashare_watch.render import export_snapshot
from ashare_watch.store import SnapshotStore
from ashare_watch.structure import to_sina_symbol

LOGGER = logging.getLogger("ashare_watch.server")

STATIC_DIR = Path(__file__).parent / "static"
POLL_HINT_SECONDS = 10

# 详情接口只接受 6 位代码（可带 sh/sz/bj 前缀）。这个代码会被拼进请求路径，
# 所以必须在入口处卡死格式，不能让它变成"随便构造 URL"的跳板。
STOCK_CODE = re.compile(r"(sh|sz|bj)?\d{6}")


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
        # 被上游限流之后的冷却截止时间（time.monotonic 口径）
        self._cooldown_until = 0.0

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
            wait = float(self.state.interval)
            if self._cooldown_until > time.monotonic():
                wait = max(wait, self._cooldown_until - time.monotonic())
            self._wake.wait(timeout=wait)
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
        limited_before = self.collector.client.stats.get("rate_limited", 0)
        try:
            snapshot = self.collector.refresh(include_universe=include_universe)
            self.state.set_snapshot(snapshot)
            # 被限流之后不要继续按 15 秒的节奏去敲门：限流窗口是按请求量续期的，
            # 越是硬敲，恢复得越慢，页面上也会长时间只剩残缺数据。
            # 这里退到冷却时间再来，用一个请求换回正常的刷新节奏。
            if self.collector.client.stats.get("rate_limited", 0) > limited_before:
                self._cooldown_until = time.monotonic() + self.collector.settings.rate_limit_cooldown
                LOGGER.warning(
                    "被上游限流，暂停刷新 %.0f 秒后再试",
                    self.collector.settings.rate_limit_cooldown,
                )
            else:
                self._cooldown_until = 0.0
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
        if path == "/api/quotes":
            # 任意代码的实时行情，供「我的关注」使用。
            # 关注列表存在浏览器本地（这样静态分享页也能用），
            # 前端每次会把需要刷新的代码通过 query 传过来，服务端不保存状态。
            query = urllib.parse.urlparse(self.path).query
            raw = urllib.parse.parse_qs(query).get("codes", [""])[0]
            symbols = [to_sina_symbol(c.strip()) for c in raw.split(",") if c.strip()]
            # 上限保护：避免有人拿这个接口当批量下载用
            symbols = symbols[:60]
            if not symbols:
                self._send_json({"quotes": []})
                return
            quotes = self.collector.client.quotes(symbols)
            self._send_json({"quotes": [q.to_dict() for q in quotes]})
            return
        if path == "/api/stock":
            # 单只股票的详情，供「点进某只股票」用。
            # 全市场 5500 只不可能每只都预先抓一份 K 线（那是 5500 个请求），
            # 但单只股票只要 4 个请求、半秒左右，点开时再抓完全来得及。
            query = urllib.parse.urlparse(self.path).query
            code = urllib.parse.parse_qs(query).get("code", [""])[0].strip().lower()
            if not STOCK_CODE.fullmatch(code):
                self._send_json({"error": "代码格式不对，应该是 6 位数字"}, 400)
                return
            self._send_json(self.collector.stock_detail(to_sina_symbol(code)))
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


class SingleInstanceServer(ThreadingHTTPServer):
    """不允许两个看板绑同一个端口。

    ``http.server`` 默认是 ``allow_reuse_address = 1``。这个选项在 Linux 上
    只是「重启后立刻复用 TIME_WAIT 的端口」，但在 Windows 上它的语义完全不同：
    **两个进程可以同时绑同一个端口**，而且先绑的那个继续收连接。

    后果非常隐蔽——双击两次 start.bat，新进程正常启动、日志也正常刷新，
    但浏览器访问到的还是旧进程的数据。你会以为是「改了代码没生效」，
    实际上是老实例一直活着。关掉这个选项，第二个实例会直接报端口占用。
    """

    allow_reuse_address = False


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
        try:
            state.snapshot = snapshot_from_dict(cached)
        except (TypeError, ValueError):
            LOGGER.warning("缓存快照结构不兼容，已忽略")

    worker = RefreshWorker(collector, state)
    Handler.state = state
    Handler.collector = collector
    Handler.worker = worker

    httpd = SingleInstanceServer((settings.host, settings.port), Handler)
    httpd.daemon_threads = True
    if start_worker:
        worker.start()
    return httpd, state, worker, collector


def running_instance(url: str) -> bool:
    """判断这个地址上是不是已经有一个看板在跑。

    只认 ``/api/health`` 返回的 ``status == "ok"``，避免把恰好占了同一个端口
    的别的程序误判成「看板已在运行」。
    """
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=2) as response:
            return json.loads(response.read().decode("utf-8")).get("status") == "ok"
    except Exception:  # noqa: BLE001 - 连不上就是没有，不需要区分原因
        return False


def serve(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    url = f"http://{settings.host}:{settings.port}"

    try:
        httpd, _state, worker, _collector = create_server(settings)
    except OSError:
        # 端口被占。绝大多数情况是用户又双击了一次 start.bat，
        # 这时候「把已经在跑的那个打开」比报一堆错有用得多。
        if running_instance(url):
            print(f"看板已经在运行了：{url}")
            print("  直接打开这个地址即可，不需要再启动一份。")
            if settings.open_browser:
                webbrowser.open(url)
            return
        print(f"[ERROR] 端口 {settings.port} 被占用，但那个程序不是本看板。")
        print("  换个端口再启动，例如： set ASHARE_WATCH_PORT=8781")
        raise

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
