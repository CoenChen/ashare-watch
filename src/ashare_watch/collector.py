"""采集编排：抓取 → 派生 → 存储，产出一份完整的仪表盘快照。"""

from __future__ import annotations

import logging
import json
import time
from datetime import datetime

from ashare_watch.client import SinaClient
from ashare_watch.config import Settings, get_settings
from ashare_watch.derive import (
    build_breadth,
    build_limit_stats,
    build_rankings,
    build_search_index,
)
from ashare_watch.market import beijing_now, market_status
from ashare_watch.models import Snapshot, snapshot_from_dict
from ashare_watch.store import SnapshotStore
from ashare_watch.structure import to_sina_symbol

LOGGER = logging.getLogger("ashare_watch.collector")

SOURCES = [
    "hq.sinajs.cn（指数与个股行情）",
    "vip.stock.finance.sina.com.cn（全市场 / 行业板块）",
    "quotes.sina.cn（指数日线）",
]

# 详情接口比快照多出来的一路数据源，写在这里方便前端/README 引用
DETAIL_SOURCES = [
    "hq.sinajs.cn（实时行情 + 买卖五档）",
    "quotes.sina.cn（日线与 5 分钟线）",
    "vip.stock.finance.sina.com.cn（资金流向）",
]


def _now() -> str:
    return beijing_now().isoformat(timespec="seconds")


class Collector:
    def __init__(
        self,
        settings: Settings | None = None,
        client: SinaClient | None = None,
        store: SnapshotStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.client = client or SinaClient(self.settings)
        self.store = store or SnapshotStore(self.settings.db_path)

    def refresh(self, *, include_universe: bool = True) -> Snapshot:
        """跑一次采集。

        所有网络请求一次性提交到同一个线程池。全市场要翻 56 页，
        串行发起会慢到不可用；并发之后只要几秒。

        任何一个数据源失败都不会中断整次采集——**部分数据也比没有数据好**。
        失败项会进 ``warnings``，前端明确提示哪部分可能不是最新的，
        而不是悄悄显示空值让人误以为市场真的没数据。
        """
        started = time.perf_counter()
        started_at = _now()
        warnings: list[str] = []
        before_requests = self.client.stats["requests"]
        before_failures = self.client.stats["failures"]

        pool = self.client.pool
        index_symbols = list(self.settings.indexes)
        # 指数与自选股合并成一次批量请求（新浪支持 list= 批量拉取）
        quote_symbols = index_symbols + [to_sina_symbol(c) for c in self.settings.symbols]
        quotes_future = pool.submit(self.client.quotes, quote_symbols)
        history_futures = {
            symbol: pool.submit(self.client.index_history, symbol, 250) for symbol in index_symbols
        }
        sectors_future = pool.submit(self.client.sectors)
        macro_future = pool.submit(self.client.macro_quotes)
        universe_future = pool.submit(self.client.universe) if include_universe else None

        quotes = quotes_future.result()
        # 用新浪代码做键：sh000001 是上证指数，sz000001 是平安银行，
        # 只用 6 位数字会把两者混为一谈。
        by_symbol = {q.sina: q for q in quotes}
        indexes = [by_symbol[s] for s in index_symbols if s in by_symbol]
        watchlist = [
            by_symbol[to_sina_symbol(c)] for c in self.settings.symbols
            if to_sina_symbol(c) in by_symbol
        ]
        if not indexes:
            warnings.append("指数行情抓取失败")
        missing = [c for c in self.settings.symbols if to_sina_symbol(c) not in by_symbol]
        if missing:
            warnings.append(f"自选股数据缺失：{', '.join(missing[:8])}")

        # 给每个指数挂上近 30 个交易日的收盘价，前端画迷你走势用
        for index_quote in indexes:
            future = history_futures.get(index_quote.sina)
            history = future.result() if future else []
            index_quote.history = [row["close"] for row in history[-30:]]

        try:
            sectors = sectors_future.result()
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("行业板块抓取失败：%s", error)
            sectors = []
            warnings.append("行业板块数据抓取失败")

        try:
            macro = macro_future.result()
        except Exception as error:  # noqa: BLE001
            LOGGER.warning("环球市场抓取失败：%s", error)
            macro = []
        if not macro:
            warnings.append("环球市场数据抓取失败（黄金 / 原油 / 外汇不可用）")

        universe = []
        if universe_future is not None:
            try:
                universe = universe_future.result()
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("全市场抓取失败：%s", error)
            if not universe:
                warnings.append("全市场数据抓取失败，榜单/宽度/涨跌停统计不可用")
            elif self.client.last_completeness < 0.98:
                # 静默少抓几十页会让榜单和涨跌家数失真，而页面上看不出异常，
                # 所以必须显式告诉用户"这次数据不完整"。
                warnings.append(
                    f"全市场数据不完整：只抓到 {self.client.last_universe_got} / "
                    f"{self.client.last_universe_expected} 只"
                    "（可能被接口限流，稍后会自动重试）"
                )
            if self.client.stats.get("rate_limited"):
                warnings.append(
                    f"本次采集遇到 {self.client.stats['rate_limited']} 次接口限流，"
                    "已自动退避重试；如果频繁出现可以把 ASHARE_WATCH_WORKERS 调小"
                )

        gainers, losers, most_active, turnover_leaders = build_rankings(universe)
        breadth = build_breadth(universe)
        limits = build_limit_stats(universe)

        # 交易日以行情里带的日期为准，可以顺带识别节假日
        trade_date = ""
        for quote in indexes:
            if quote.timestamp:
                trade_date = quote.timestamp
                break
        status = market_status(trade_date=trade_date)

        snapshot = Snapshot(
            fetched_at=_now(),
            generated_ms=(time.perf_counter() - started) * 1000,
            market=status,
            indexes=indexes,
            watchlist=watchlist,
            gainers=gainers,
            losers=losers,
            most_active=most_active,
            turnover_leaders=turnover_leaders,
            sectors=sectors,
            macro=macro,
            breadth=breadth,
            limits=limits,
            coverage={
                "universe": len(universe),
                "watchlist": len(watchlist),
                "indexes": len(indexes),
                "sectors": len(sectors),
                "macro": len(macro),
            },
            index_history=self.client.index_history("sh000001", 250),
            warnings=warnings,
            sources=SOURCES,
        )

        self.store.save_snapshot(snapshot.to_dict())
        self.store.log_run(
            started_at=started_at,
            finished_at=_now(),
            status="ok" if not warnings else "partial",
            duration_ms=(time.perf_counter() - started) * 1000,
            requests=self.client.stats["requests"] - before_requests,
            failures=self.client.stats["failures"] - before_failures,
            market_status=status.status,
            message="；".join(warnings),
        )
        LOGGER.info(
            "采集完成：%d 指数 / %d 自选股 / %d 只全市场 / %d 板块，耗时 %.1fs",
            len(indexes), len(watchlist), len(universe), len(sectors),
            snapshot.generated_ms / 1000,
        )
        return snapshot

    def stock_detail(self, symbol: str) -> dict:
        """单只股票的详情。**只在用户点开某只股票时调用，不进快照。**

        为什么不预先抓：全市场 5500 多只，每只一份 K 线就是 5500 多个请求，
        既慢又会把接口撞进限流。而单只股票只有 4 个请求、半秒左右，
        用户点开的瞬间去抓完全来得及——这就是「按需抓取」的取舍。
        """
        detail = self.client.stock_detail(symbol)
        detail["fetched_at"] = _now()
        detail["sources"] = DETAIL_SOURCES
        return detail

    def search_index(self) -> list[list]:
        """搜索用的精简全市场索引。

        刻意**不放进快照**：快照每 15 秒被 API 序列化一次、还要写进 SQLite
        保留 500 份，塞进 200 多 KB 的索引会让数据库膨胀到上百 MB。
        这里单独成接口，前端加载一次、每几分钟刷新一次就够了。

        ``client.universe()`` 命中 TTL 缓存时几乎是零成本的，
        所以前端频繁问也不会带来额外请求。

        另外会把结果缓存在 ``data/search-index.json``：**离线构建时（比如
        CI 里抓取失败、或本机断网）可以退回上一次的索引**，而不是让
        分享出去的页面直接失去搜索能力。
        """
        rows = build_search_index(self.client.universe())
        if rows:
            try:
                self.settings.ensure_dirs()
                self.settings.search_index_path.write_text(
                    json.dumps(rows, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                    newline="\n",
                )
            except OSError as error:
                LOGGER.warning("搜索索引缓存写入失败：%s", error)
            return rows

        # 抓不到全市场数据（断网 / 被限流）：退回上次的索引
        cached = self._load_cached_search_index()
        if cached:
            LOGGER.warning("全市场数据不可用，搜索索引退回本地缓存（%d 条）", len(cached))
        return cached

    def _load_cached_search_index(self) -> list[list]:
        path = self.settings.search_index_path
        if not path.exists():
            return []
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return rows if isinstance(rows, list) else []

    def cached_or_refresh(self) -> Snapshot:
        cached = self.store.latest_snapshot()
        if cached:
            try:
                return snapshot_from_dict(cached)
            except (TypeError, ValueError):
                LOGGER.warning("缓存快照结构不兼容，改为重新抓取")
        return self.refresh()
