"""数据源客户端。

四个数据源，全部是公开接口，并且都经过实测验证：

===============================  ==========================================
接口                              用途
===============================  ==========================================
hq.sinajs.cn                     指数与个股实时行情（批量，GBK）
Market_Center.getHQNodeData      全市场分页快照（榜单 / 宽度 / 涨跌停）
Market_Center.getHQNodeStockCount 全市场股票数量（决定翻多少页）
newSinaHy.php                     行业板块涨跌幅（官方行业分类）
CN_MarketDataService.getKLineData 指数日线历史
===============================  ==========================================

两个关键工程细节，都是从上一个项目踩坑里总结出来的：

1. **连接复用**。国内访问这些接口，单个请求的接口耗时只有 0.2–0.6 秒，
   但每次新建 TLS 连接要多花好几秒。全市场要翻 56 页，不复用连接根本跑不动。
   这里用线程本地存储为**每个域名**各持一条长连接。
2. **批量而不是逐个**。指数和自选股用 `list=` 一次请求拿完，
   全市场用接口自带的分页 + 排序，而不是逐个股票去查。
"""

from __future__ import annotations

import http.client
import json
import logging
import ssl
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from ashare_watch.config import (
    MACRO_UNITS,
    Settings,
    get_settings,
    macro_group_of,
    macro_name_of,
)
from ashare_watch.market import board_of, detect_limit, is_st
from ashare_watch.models import MacroQuote, Quote, SectorStat
from ashare_watch.structure import (
    decode_gbk,
    digits_for,
    macro_fields,
    parse_js_object,
    parse_json_array,
    parse_number,
    parse_percent,
    parse_compact,
    parse_sina_quotes,
    quote_fields,
    short_code,
    is_index_symbol,
    to_sina_symbol,
)

LOGGER = logging.getLogger("ashare_watch.client")

HOST_QUOTE = "hq.sinajs.cn"
HOST_VIP = "vip.stock.finance.sina.com.cn"
HOST_KLINE = "quotes.sina.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://finance.sina.com.cn/",
    "Connection": "keep-alive",
}

RANK_SORTS = {
    "changepercent": "changepercent",
    "amount": "amount",
    "turnoverratio": "turnoverratio",
}

# 这两个状态码表示"你请求太频繁"，不是数据本身有问题。
# 遇到它们时继续重试只会让限流窗口变长，正确做法是退避后少试一次。
RATE_LIMIT_STATUS = {429, 456}


class SinaClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._local = threading.local()
        self._last_request_at = 0.0
        self._cache: dict[str, tuple[float, object]] = {}
        self._pool = ThreadPoolExecutor(max_workers=max(2, self.settings.workers))
        self.stats = {
            "requests": 0,
            "failures": 0,
            "cache_hits": 0,
            "bytes": 0,
            "rate_limited": 0,
        }
        # 全市场抓取的完整性，供上层写进 warnings
        self.last_universe_expected = 0
        self.last_universe_got = 0
        self.last_completeness = 1.0
        # 连续失败计数：断网时用它熔断，避免把 56 页全试一遍再退回缓存。
        # 每个请求失败要重试 3 次并退避，56 页累计能拖到两分钟以上。
        self._failure_streak = 0

    @property
    def failure_streak(self) -> int:
        return self._failure_streak

    @property
    def pool(self) -> ThreadPoolExecutor:
        return self._pool

    # ------------------------------------------------------------------ #
    # 底层请求（每个域名一条长连接）
    # ------------------------------------------------------------------ #
    def _throttle(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = self.settings.min_request_interval - elapsed
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    def _connection(self, host: str) -> http.client.HTTPSConnection:
        connections = getattr(self._local, "connections", None)
        if connections is None:
            connections = {}
            self._local.connections = connections
        connection = connections.get(host)
        if connection is None:
            connection = http.client.HTTPSConnection(
                host, timeout=self.settings.timeout, context=ssl.create_default_context()
            )
            connections[host] = connection
        return connection

    def _drop_connection(self, host: str) -> None:
        connections = getattr(self._local, "connections", None)
        if connections and host in connections:
            try:
                connections[host].close()
            except Exception:  # noqa: BLE001
                pass
            connections[host] = None

    def _request(self, host: str, path: str, params: dict | None = None) -> bytes | None:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        target = f"{path}{query}"
        last_error = ""
        for attempt in range(self.settings.retries):
            self._throttle()
            self.stats["requests"] += 1
            try:
                connection = self._connection(host)
                connection.request("GET", target, headers={**HEADERS, "Host": host})
                response = connection.getresponse()
                raw = response.read()
                if response.status in RATE_LIMIT_STATUS:
                    # 被限流。继续快速重试只会让限流窗口更长，所以这里退避
                    # 一段时间，并且只再试一次就放弃。
                    self._drop_connection(host)
                    self.stats["rate_limited"] += 1
                    last_error = f"HTTP {response.status}（被限流）"
                    LOGGER.warning(
                        "被限流，退避 %.1fs：%s%s",
                        self.settings.rate_limit_backoff, host, target[:60],
                    )
                    if attempt < 1:
                        time.sleep(self.settings.rate_limit_backoff)
                        continue
                    break
                if response.status != 200:
                    self._drop_connection(host)
                    last_error = f"HTTP {response.status}"
                    if response.status in (400, 403, 404):
                        break
                else:
                    self.stats["bytes"] += len(raw)
                    self._failure_streak = 0
                    return raw
            except (http.client.HTTPException, urllib.error.URLError, TimeoutError,
                    OSError, ssl.SSLError) as error:
                last_error = f"{type(error).__name__}: {error}"
                self._drop_connection(host)
            # 已经连续失败很多次，多半是断网或被限流，剩下的重试只是白等
            if self._failure_streak >= 5:
                break
            if attempt < self.settings.retries - 1:
                time.sleep(0.8 * (2**attempt))

        self._failure_streak += 1
        self.stats["failures"] += 1
        LOGGER.warning("请求失败 %s%s（%s）", host, target[:90], last_error)
        return None

    def _cached(self, key: str, ttl: float, producer):
        """带 TTL 的缓存；抓取失败时回退到过期数据而不是返回空。"""
        now = time.monotonic()
        entry = self._cache.get(key)
        if entry and now - entry[0] < ttl:
            self.stats["cache_hits"] += 1
            return entry[1]
        value = producer()
        if value:
            self._cache[key] = (now, value)
            return value
        if entry:
            LOGGER.warning("抓取失败，回退到过期缓存：%s", key)
            return entry[1]
        return None

    def cache_age(self, key: str) -> float | None:
        entry = self._cache.get(key)
        return None if entry is None else time.monotonic() - entry[0]

    # ------------------------------------------------------------------ #
    # 实时行情（批量）
    # ------------------------------------------------------------------ #
    def quotes(self, symbols: list[str], chunk_size: int = 50) -> list[Quote]:
        """一次请求拿多只标的。``symbols`` 用新浪格式（sh600519）。

        新浪单次请求的标的数量有限，这里按 50 个一组分批。
        指数和个股的字段布局一致，所以可以混在同一个请求里。
        """
        if not symbols:
            return []
        unique = list(dict.fromkeys(symbols))
        chunks = [unique[i : i + chunk_size] for i in range(0, len(unique), chunk_size)]

        def fetch(chunk: list[str]) -> dict[str, list[str]]:
            raw = self._request(HOST_QUOTE, "/list=" + ",".join(chunk))
            return parse_sina_quotes(decode_gbk(raw)) if raw else {}

        futures = [self._pool.submit(fetch, chunk) for chunk in chunks]
        merged: dict[str, list[str]] = {}
        for future in futures:
            try:
                merged.update(future.result())
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("批量行情分批失败：%s", error)

        out: list[Quote] = []
        for symbol in symbols:
            fields = merged.get(symbol)
            if not fields:
                continue
            out.append(self._build_quote(symbol, fields))
        return out

    def _build_quote(self, symbol: str, fields: list[str]) -> Quote:
        data = quote_fields(fields)
        code = short_code(symbol)
        name = str(data["name"])
        rule = board_of(code)
        quote = Quote(
            code=code,
            sina=symbol,
            name=name,
            price=data["price"],          # type: ignore[arg-type]
            change=data["change"],        # type: ignore[arg-type]
            change_pct=data["change_pct"],  # type: ignore[arg-type]
            open=data["open"],            # type: ignore[arg-type]
            prev_close=data["prev_close"],  # type: ignore[arg-type]
            high=data["high"],            # type: ignore[arg-type]
            low=data["low"],              # type: ignore[arg-type]
            volume=data["volume"],        # type: ignore[arg-type]
            amount=data["amount"],        # type: ignore[arg-type]
            board=rule.name,
            is_st=is_st(name),
            timestamp=str(data["timestamp"]),
        )
        # 指数没有涨跌停概念，只有个股才判断
        if not is_index_symbol(symbol):
            quote.limit_status = detect_limit(
                code=code,
                name=name,
                change_pct=quote.change_pct,
                price=quote.price,
                open_price=quote.open,
                high=quote.high,
                low=quote.low,
            )
        return quote

    # ------------------------------------------------------------------ #
    # 全市场分页快照
    # ------------------------------------------------------------------ #
    def universe_count(self) -> int:
        """全市场股票数量，用来决定翻多少页。"""
        raw = self._request(
            HOST_VIP,
            "/quotes_service/api/json_v2.php/Market_Center.getHQNodeStockCount",
            {"node": "hs_a"},
        )
        if not raw:
            return 0
        text = decode_gbk(raw).strip().strip('"')
        return int(text) if text.isdigit() else 0

    def universe_page(self, page: int, sort: str = "changepercent", asc: int = 0) -> list[Quote]:
        """按指定排序取一页全市场数据。接口自带排序，所以不需要本地排序。"""
        raw = self._request(
            HOST_VIP,
            "/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
            {
                "page": page,
                "num": self.settings.page_size,
                "sort": RANK_SORTS.get(sort, sort),
                "asc": asc,
                "node": "hs_a",
            },
        )
        if not raw:
            return []
        rows = parse_json_array(decode_gbk(raw))
        out: list[Quote] = []
        for row in rows:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            name = str(row.get("name") or "").strip()
            rule = board_of(code)
            price = parse_number(row.get("trade"))
            prev_close = parse_number(row.get("settlement"))
            change_pct = parse_number(row.get("changepercent"))
            quote = Quote(
                code=code,
                sina=to_sina_symbol(code),
                name=name,
                price=price,
                change=parse_number(row.get("pricechange")),
                change_pct=change_pct,
                open=parse_number(row.get("open")),
                prev_close=prev_close,
                high=parse_number(row.get("high")),
                low=parse_number(row.get("low")),
                volume=parse_number(row.get("volume")),
                amount=parse_number(row.get("amount")),
                turnover=parse_number(row.get("turnoverratio")),
                pe=parse_number(row.get("per")),
                pb=parse_number(row.get("pb")),
                market_cap=parse_compact(row.get("mktcap")),
                float_cap=parse_compact(row.get("nmc")),
                board=rule.name,
                is_st=is_st(name),
                timestamp=str(row.get("ticktime") or ""),
            )
            quote.limit_status = detect_limit(
                code=code,
                name=name,
                change_pct=quote.change_pct,
                price=quote.price,
                open_price=quote.open,
                high=quote.high,
                low=quote.low,
            )
            out.append(quote)
        return out

    def universe(self) -> list[Quote]:
        """抓取整个沪深 A 股快照（约 5500 只，56 页）。

        这是榜单、市场宽度、涨跌停统计的共同数据源。

        这里做了**完整性校验**：第一轮并发抓完之后，如果页数明显不够
        （被限流、超时等），会用更慢的节奏把缺的页补一遍。
        这一步很重要——静默少抓几十页，会直接导致榜单和涨跌家数失真，
        而页面上看不出任何异常。补抓之后仍然不完整的话，
        会记进 ``last_completeness``，由上层写进 warnings 告诉用户。
        """

        def produce() -> list[Quote]:
            expected = self.universe_count() or 5600
            pages = max(1, (expected + self.settings.page_size - 1) // self.settings.page_size)
            merged: dict[str, Quote] = {}

            missing = self._fetch_pages(range(1, pages + 1), merged)

            if missing:
                # 第一轮缺页：等限流窗口过去，再用更慢的节奏补一次
                LOGGER.info("首轮缺 %d 页，退避后补抓", len(missing))
                time.sleep(1.5)
                missing = self._fetch_pages(missing, merged, delay=0.4)

            self.last_universe_expected = expected
            self.last_universe_got = len(merged)
            self.last_completeness = (
                min(1.0, len(merged) / expected) if expected else 0.0
            )
            if missing:
                LOGGER.warning("全市场数据仍不完整，缺 %d 页", len(missing))
            return list(merged.values())

        return self._cached("universe", self.settings.universe_ttl, produce) or []

    def _fetch_pages(
        self, pages, merged: dict[str, Quote], *, delay: float = 0.0
    ) -> list[int]:
        """抓取指定页并合并到 ``merged``，返回仍然缺失的页码。

        ``delay > 0`` 时切换成**慢速逐页模式**，专门用于补抓被限流的页：
        一页一页发、每页之间留间隔，而不是再一次并发冲击对端。
        """
        page_list = list(pages)

        if delay:
            slow_missing: list[int] = []
            for index, page in enumerate(page_list):
                # 熔断：前面已经连续失败很多次，这一轮剩下的页没必要再试
                if self._failure_streak >= 5:
                    slow_missing.extend(page_list[index:])
                    break
                try:
                    rows = self.universe_page(page, "changepercent", 0)
                except Exception as error:  # noqa: BLE001
                    LOGGER.warning("全市场第 %d 页补抓失败：%s", page, error)
                    rows = []
                if not rows:
                    slow_missing.append(page)
                else:
                    for quote in rows:
                        merged[quote.code] = quote
                time.sleep(delay)
            return slow_missing

        futures = {
            page: self._pool.submit(self.universe_page, page, "changepercent", 0)
            for page in page_list
        }
        missing: list[int] = []
        for index, page in enumerate(page_list):
            try:
                rows = futures[page].result()
            except Exception as error:  # noqa: BLE001
                LOGGER.warning("全市场第 %d 页失败：%s", page, error)
                rows = []
            if not rows:
                missing.append(page)
                # 熔断：连续失败说明网络不通或被限流。把剩余页直接标记为缺失，
                # 而不是让 56 页各自重试三遍——实测那样能拖到两分钟以上。
                if self._failure_streak >= 5:
                    missing.extend(page_list[index + 1 :])
                    LOGGER.warning("连续失败达 %d 次，中止本轮全市场抓取", self._failure_streak)
                    break
                continue
            for quote in rows:
                merged[quote.code] = quote
        return missing

    # ------------------------------------------------------------------ #
    # 行业板块
    # ------------------------------------------------------------------ #
    def macro_quotes(self, symbols: list[str] | None = None) -> list[MacroQuote]:
        """环球市场行情：贵金属、能源、基本金属、国内期货、海外股指、外汇、数字货币。

        和 A 股行情同一个域名，所以可以批量拿，只是**解析规则不同**
        （外盘期货、国内期货、外汇、美元指数是四套字段布局，
        见 ``structure.macro_fields``）。

        品种超过 ``MACRO_CHUNK_SIZE`` 时会拆成几批并发取：新浪的 ``list=``
        是拼在 URL 里的，五十多个代码压成一条超长 URL 有被截断的风险。
        拆分只多一个请求，比赌 URL 不被截断划算。
        """
        symbols = list(symbols or self.settings.macro_symbols)
        if not symbols:
            return []

        unique = list(dict.fromkeys(symbols))
        size = max(1, self.settings.macro_chunk_size)
        chunks = [unique[i : i + size] for i in range(0, len(unique), size)]

        def fetch(chunk: list[str]) -> dict[str, list[str]]:
            raw = self._request(HOST_QUOTE, "/list=" + ",".join(chunk))
            return parse_sina_quotes(decode_gbk(raw)) if raw else {}

        parsed: dict[str, list[str]] = {}
        if len(chunks) == 1:
            # 常见情况就是一批，不必为了它去开线程池
            parsed = fetch(chunks[0])
        else:
            futures = [self._pool.submit(fetch, chunk) for chunk in chunks]
            for future in futures:
                try:
                    parsed.update(future.result())
                except Exception as error:  # noqa: BLE001
                    LOGGER.warning("环球市场分批失败：%s", error)

        out: list[MacroQuote] = []
        for symbol in symbols:
            fields = parsed.get(symbol)
            if not fields:
                continue
            data = macro_fields(symbol, fields)
            price = data.get("price")
            prev_close = data.get("prev_close")
            change = data.get("change")
            change_pct = data.get("change_pct")
            # 外汇接口自带涨跌幅；外盘期货和美元指数只给昨收，需要自己算
            if change is None and price is not None and prev_close:
                change = round(price - prev_close, 6)
            if change_pct is None and change is not None and prev_close:
                change_pct = round(change / prev_close * 100, 4)

            out.append(
                MacroQuote(
                    symbol=symbol,
                    name=macro_name_of(symbol),
                    group=macro_group_of(symbol),
                    price=price,          # type: ignore[arg-type]
                    change=change,        # type: ignore[arg-type]
                    change_pct=change_pct,  # type: ignore[arg-type]
                    prev_close=prev_close,  # type: ignore[arg-type]
                    high=data.get("high"),  # type: ignore[arg-type]
                    low=data.get("low"),    # type: ignore[arg-type]
                    unit=MACRO_UNITS.get(symbol, ""),
                    digits=digits_for(price),  # type: ignore[arg-type]
                    time=str(data.get("time") or ""),
                    date=str(data.get("date") or ""),
                )
            )
        return out

    def sectors(self) -> list[SectorStat]:
        """新浪官方行业分类的板块涨跌幅。

        返回的 JS 对象里，每个值是一串逗号分隔的字段：
        代码,名称,公司家数,平均价,平均涨跌额,涨跌幅,总成交量,总成交额,
        领涨股代码,领涨股涨跌幅,领涨股现价,领涨股涨跌额,领涨股名称
        """

        def produce() -> list[SectorStat]:
            raw = self._request(HOST_VIP, "/q/view/newSinaHy.php")
            if not raw:
                return []
            payload = parse_js_object(decode_gbk(raw))
            out: list[SectorStat] = []
            for value in payload.values():
                parts = value.split(",")
                if len(parts) < 13:
                    continue
                change_pct = parse_number(parts[5])
                if change_pct is None:
                    continue
                out.append(
                    SectorStat(
                        code=parts[0].strip(),
                        name=parts[1].strip(),
                        company_count=int(parse_number(parts[2]) or 0),
                        amount=parse_number(parts[7]),
                        change_pct=change_pct,
                        leader_code=parts[8].strip(),
                        leader_change_pct=parse_number(parts[9]),
                        leader_name=parts[12].strip(),
                    )
                )
            out.sort(key=lambda item: item.change_pct, reverse=True)
            return out

        return self._cached("sectors", self.settings.sector_ttl, produce) or []

    # ------------------------------------------------------------------ #
    # 指数日线
    # ------------------------------------------------------------------ #
    def index_history(self, symbol: str = "sh000001", days: int = 250) -> list[dict]:
        """指数日线，用于画走势图和迷你走势。默认缓存 6 小时。"""
        key = f"kline:{symbol}"

        def produce() -> list[dict]:
            raw = self._request(
                HOST_KLINE,
                "/cn/api/json_v2.php/CN_MarketDataService.getKLineData",
                {"symbol": symbol, "scale": 240, "ma": "no", "datalen": 250},
            )
            if not raw:
                return []
            try:
                rows = json.loads(decode_gbk(raw).strip())
            except json.JSONDecodeError:
                return []
            out: list[dict] = []
            for row in rows if isinstance(rows, list) else []:
                close = parse_number(row.get("close"))
                if close is None:
                    continue
                out.append(
                    {
                        "date": str(row.get("day") or ""),
                        "close": close,
                        "open": parse_number(row.get("open")),
                        "high": parse_number(row.get("high")),
                        "low": parse_number(row.get("low")),
                        "volume": parse_number(row.get("volume")),
                    }
                )
            return out

        rows = self._cached(key, self.settings.history_ttl, produce) or []
        return rows[-days:] if days < len(rows) else rows

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
