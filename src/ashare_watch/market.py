"""A 股交易规则。

这里集中处理三件美股看板里不存在、但 A 股看板必须做对的事：

1. **交易时段**。A 股一天是两个连续竞价时段（9:30–11:30、13:00–15:00），
   中间有午间休市。北京时间没有夏令时，所以直接按 UTC+8 计算即可，
   不像美股需要处理时区库。但要注意运行机器不一定在中国时区，
   所以一律用 UTC 换算，不读本机时区。
2. **板块与涨跌停幅度**。主板 ±10%、创业板/科创板 ±20%、北交所 ±30%，
   主板 ST 股 ±5%。判断"是否涨停"必须先知道这只股票属于哪个板。
3. **一字板**。开盘即封板（开=高=低=收），是 A 股短线最重要的盘面信号之一，
   普通涨跌停和一字板在含义上完全不同，必须区分。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from ashare_watch.models import MarketStatus

# 北京时间固定 UTC+8，没有夏令时
BEIJING = timezone(timedelta(hours=8))

SESSION_MORNING = (time(9, 30), time(11, 30))
SESSION_AFTERNOON = (time(13, 0), time(15, 0))
AUCTION_OPEN = (time(9, 15), time(9, 25))


def beijing_now() -> datetime:
    """当前北京时间。用 UTC 换算而不是读本机时区，换台电脑也不会算错。"""
    return datetime.now(timezone.utc).astimezone(BEIJING)


def market_status(now: datetime | None = None, trade_date: str = "") -> MarketStatus:
    """按北京时间判断当前处于哪个交易阶段。"""
    now = now or beijing_now()
    today = now.date().isoformat()

    # 周末必休市
    if now.weekday() >= 5:
        return MarketStatus(
            status="休市", is_open=False, trade_date=trade_date or today, note="周末"
        )

    current = now.time()
    if AUCTION_OPEN[0] <= current < SESSION_MORNING[0]:
        return MarketStatus(status="集合竞价", is_open=False, trade_date=today)
    if SESSION_MORNING[0] <= current < SESSION_MORNING[1]:
        return MarketStatus(status="交易中", is_open=True, session="上午盘", trade_date=today)
    if SESSION_MORNING[1] <= current < SESSION_AFTERNOON[0]:
        return MarketStatus(status="午间休市", is_open=False, trade_date=today)
    if SESSION_AFTERNOON[0] <= current < SESSION_AFTERNOON[1]:
        return MarketStatus(status="交易中", is_open=True, session="下午盘", trade_date=today)

    note = ""
    # 数据源给的交易日不是今天，说明今天是节假日（接口不会返回"今天休市"这个字段）
    if trade_date and trade_date[:10] != today:
        note = f"最近交易日 {trade_date[:10]}"
    return MarketStatus(status="已收盘", is_open=False, trade_date=trade_date or today, note=note)


@dataclass(frozen=True, slots=True)
class BoardRule:
    name: str
    limit_pct: float


def board_of(code: str) -> BoardRule:
    """按 6 位代码判断所属板块与涨跌停幅度。"""
    code = code.strip()
    if code.startswith(("688", "689")):
        return BoardRule("科创板", 20.0)
    if code.startswith(("300", "301", "302")):
        return BoardRule("创业板", 20.0)
    if code.startswith(("8", "4", "92")):
        return BoardRule("北交所", 30.0)
    if code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return BoardRule("主板", 10.0)
    return BoardRule("其他", 10.0)


def is_st(name: str) -> bool:
    """ST / *ST 是风险警示股，主板涨跌停幅度收窄到 5%。"""
    upper = name.upper().replace(" ", "")
    return "ST" in upper


def limit_pct(code: str, name: str = "") -> float:
    """该股票的涨跌停幅度（百分数）。"""
    rule = board_of(code)
    if rule.name == "主板" and is_st(name):
        return 5.0
    return rule.limit_pct


def detect_limit(
    *,
    code: str,
    name: str,
    change_pct: float | None,
    price: float | None,
    open_price: float | None,
    high: float | None,
    low: float | None,
    tolerance: float = 0.15,
) -> str:
    """判断是否涨停/跌停，并区分一字板。

    ``tolerance`` 是容差：交易所的涨跌停价会四舍五入到分，
    所以实际涨跌幅常常是 9.97%、20.02% 这种数，不能按等号判断。
    """
    if change_pct is None or price is None or price <= 0:
        return ""
    limit = limit_pct(code, name)
    if change_pct >= limit - tolerance:
        direction = "涨停"
    elif change_pct <= -(limit - tolerance):
        direction = "跌停"
    else:
        return ""

    # 一字板：开盘即封死，全天没有波动
    values = [open_price, high, low, price]
    if all(v is not None and v > 0 for v in values) and len(set(values)) == 1:
        return "一字" + direction
    return direction

