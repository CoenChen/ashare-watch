"""数据结构。

抓取层与展示层之间用一套干净的自有结构，不把数据源的原始字段透传到前端——
数据源改格式时只需要改一处解析代码。

注意 A 股特有的字段：``turnover``（换手率）和 ``limit_status``（涨停/跌停）
是 A 股看板的核心指标，在美股看板里没有对应概念。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Quote:
    """一条行情。数值字段缺失统一用 ``None``，展示层渲染成 ``—``。"""

    code: str
    sina: str = ""
    name: str = ""
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    open: float | None = None
    prev_close: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    amount: float | None = None
    turnover: float | None = None
    pe: float | None = None
    pb: float | None = None
    market_cap: float | None = None
    float_cap: float | None = None
    board: str = ""
    is_st: bool = False
    limit_status: str = ""
    timestamp: str = ""
    history: list[float] = field(default_factory=list)

    @property
    def direction(self) -> str:
        if self.change_pct is None:
            return "flat"
        if self.change_pct > 0.0001:
            return "up"
        if self.change_pct < -0.0001:
            return "down"
        return "flat"

    @property
    def is_suspended(self) -> bool:
        """停牌判定：没有成交价或没有成交量。"""
        return not self.price or self.price <= 0 or not self.volume

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction
        data["is_suspended"] = self.is_suspended
        return data


@dataclass(slots=True)
class MarketStatus:
    """A 股市场状态。北京时间没有夏令时，直接按 UTC+8 计算即可。"""

    status: str = "Unknown"
    is_open: bool = False
    session: str = ""
    trade_date: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MacroQuote:
    """环球市场行情（黄金、原油、外汇、基本金属）。

    单独一个结构而不是复用 ``Quote``，因为两者的语义差别不小：

    * 这些品种**没有涨跌停**，方向判断只看涨跌；
    * 它们的**小数位差别很大**——美元指数 100.16 要 2 位，
      美元人民币 6.7065 要 4 位，用同一套格式会很难看；
    * 需要**计价单位**（美元/盎司、美元/桶、美元/吨），
      否则单看数字判断不了量级是否正常。
    """

    symbol: str
    name: str = ""
    group: str = ""
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    prev_close: float | None = None
    high: float | None = None
    low: float | None = None
    unit: str = ""
    digits: int = 2
    time: str = ""
    date: str = ""

    @property
    def direction(self) -> str:
        if self.change_pct is None:
            return "flat"
        if self.change_pct > 0.0001:
            return "up"
        if self.change_pct < -0.0001:
            return "down"
        return "flat"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["direction"] = self.direction
        return data


@dataclass(slots=True)
class SectorStat:
    """行业板块统计，直接采用新浪官方行业分类的涨跌幅。"""

    name: str
    code: str
    change_pct: float
    company_count: int
    amount: float | None = None
    leader_name: str = ""
    leader_code: str = ""
    leader_change_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Snapshot:
    """一次完整的仪表盘数据快照。"""

    fetched_at: str = ""
    generated_ms: float = 0.0
    market: MarketStatus = field(default_factory=MarketStatus)
    indexes: list[Quote] = field(default_factory=list)
    watchlist: list[Quote] = field(default_factory=list)
    gainers: list[Quote] = field(default_factory=list)
    losers: list[Quote] = field(default_factory=list)
    most_active: list[Quote] = field(default_factory=list)
    turnover_leaders: list[Quote] = field(default_factory=list)
    sectors: list[SectorStat] = field(default_factory=list)
    macro: list[MacroQuote] = field(default_factory=list)
    breadth: dict[str, int] = field(default_factory=dict)
    limits: dict[str, int] = field(default_factory=dict)
    coverage: dict[str, int] = field(default_factory=dict)
    index_history: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at,
            "generated_ms": round(self.generated_ms, 1),
            "market": self.market.to_dict(),
            "indexes": [q.to_dict() for q in self.indexes],
            "watchlist": [q.to_dict() for q in self.watchlist],
            "gainers": [q.to_dict() for q in self.gainers],
            "losers": [q.to_dict() for q in self.losers],
            "most_active": [q.to_dict() for q in self.most_active],
            "turnover_leaders": [q.to_dict() for q in self.turnover_leaders],
            "sectors": [s.to_dict() for s in self.sectors],
            "macro": [m.to_dict() for m in self.macro],
            "breadth": self.breadth,
            "limits": self.limits,
            "coverage": self.coverage,
            "index_history": self.index_history,
            "warnings": self.warnings,
            "sources": self.sources,
        }


def snapshot_from_dict(data: dict[str, Any]) -> Snapshot:
    """把 JSON（也就是从 SQLite 读回来的快照）还原成 Snapshot 对象。

    为什么要专门写这个：``Snapshot(**data)`` 看起来能用，但 ``market`` 在 JSON
    里是普通 dict，而 ``Snapshot.to_dict()`` 里写的是 ``self.market.to_dict()``、
    刷新调度里写的是 ``self.snapshot.market.is_open``——两处都会直接抛
    AttributeError。表现是「刚启动的那一瞬间接口 500」，而且只有缓存快照被
    真正用到时（第一次抓取还没回来的那几秒）才出现，非常难复现。
    """
    def items_of(key: str, cls: type) -> list:
        return [
            cls(**{k: v for k, v in item.items() if k in cls.__dataclass_fields__})
            for item in (data.get(key) or [])
            if isinstance(item, dict)
        ]

    market_data = data.get("market")
    market = (
        MarketStatus(
            **{k: v for k, v in market_data.items() if k in MarketStatus.__dataclass_fields__}
        )
        if isinstance(market_data, dict)
        else MarketStatus()
    )

    def mapping(key: str) -> dict:
        value = data.get(key)
        return dict(value) if isinstance(value, dict) else {}

    return Snapshot(
        fetched_at=str(data.get("fetched_at") or ""),
        generated_ms=float(data.get("generated_ms") or 0.0),
        market=market,
        indexes=items_of("indexes", Quote),
        watchlist=items_of("watchlist", Quote),
        gainers=items_of("gainers", Quote),
        losers=items_of("losers", Quote),
        most_active=items_of("most_active", Quote),
        turnover_leaders=items_of("turnover_leaders", Quote),
        sectors=items_of("sectors", SectorStat),
        macro=items_of("macro", MacroQuote),
        breadth=mapping("breadth"),
        limits=mapping("limits"),
        coverage=mapping("coverage"),
        index_history=list(data.get("index_history") or []),
        warnings=[str(item) for item in (data.get("warnings") or [])],
        sources=[str(item) for item in (data.get("sources") or [])],
    )
