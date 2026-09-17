"""派生指标：榜单、市场宽度、涨跌停统计。

全部从**一份全市场快照**本地算出来，不额外请求接口。这样一次分页抓取
就同时支撑了四个榜单、市场宽度和涨跌停统计。

过滤规则需要解释一下，因为它们直接影响榜单有没有参考价值：

* 剔除停牌股（没有成交价或成交量为 0）。否则它们会以 0.00% 混进"平盘"，
  把涨跌家数的口径搞乱。
* 剔除新股首日与次新股（名称以 ``N`` / ``C`` 开头）。它们不受
  ±10% / ±20% 涨跌停限制，动辄 +300%，会完全盖住真实的市场结构。
"""

from __future__ import annotations

from ashare_watch.models import Quote

DEFAULT_LIMIT = 15
# 一字板单独统计：开盘即封死，和普通涨跌停的含义完全不同
LIMIT_LABELS = ("涨停", "跌停", "一字涨停", "一字跌停")


def tradable(universe: list[Quote]) -> list[Quote]:
    """过滤掉不适合进入榜单的标的（停牌、新股、缺数据）。"""
    out: list[Quote] = []
    for quote in universe:
        if quote.change_pct is None or not quote.price or quote.price <= 0:
            continue
        if quote.is_suspended:
            continue
        name = quote.name.strip()
        if name[:1].upper() in ("N", "C"):
            continue
        out.append(quote)
    return out


def build_rankings(
    universe: list[Quote], limit: int = DEFAULT_LIMIT
) -> tuple[list[Quote], list[Quote], list[Quote], list[Quote]]:
    """返回 ``(涨幅榜, 跌幅榜, 成交额榜, 换手率榜)``。"""
    pool = tradable(universe)
    gainers = sorted(pool, key=lambda q: q.change_pct or 0.0, reverse=True)[:limit]
    losers = sorted(pool, key=lambda q: q.change_pct or 0.0)[:limit]
    active = sorted(pool, key=lambda q: q.amount or 0.0, reverse=True)[:limit]
    turnover = sorted(pool, key=lambda q: q.turnover or 0.0, reverse=True)[:limit]
    return gainers, losers, active, turnover


def build_breadth(universe: list[Quote]) -> dict[str, int]:
    """市场宽度：涨跌家数。比单看指数点位更能反映市场真实强弱。"""
    advancers = decliners = unchanged = 0
    for quote in universe:
        if quote.change_pct is None or quote.is_suspended:
            continue
        if quote.change_pct > 0.0001:
            advancers += 1
        elif quote.change_pct < -0.0001:
            decliners += 1
        else:
            unchanged += 1
    total = advancers + decliners + unchanged
    return {
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "total": total,
        "ratio": round(advancers / total, 4) if total else 0.0,
    }


def build_limit_stats(universe: list[Quote]) -> dict[str, int]:
    """涨跌停统计。

    这是 A 股独有的、也是最有信息量的情绪指标之一：涨停家数反映资金进攻意愿，
    跌停家数反映恐慌程度，而一字涨停家数则说明有资金在抢筹。
    """
    stats = {label: 0 for label in LIMIT_LABELS}
    stats["涨停家数"] = 0
    stats["跌停家数"] = 0
    for quote in universe:
        status = quote.limit_status
        if not status:
            continue
        stats[status] = stats.get(status, 0) + 1
        if "涨" in status:
            stats["涨停家数"] += 1
        else:
            stats["跌停家数"] += 1
    # 炸板（曾涨停但未封住）用最高价触及涨停、收盘未涨停来近似
    broken = 0
    for quote in universe:
        if quote.limit_status or quote.is_suspended:
            continue
        if quote.high and quote.prev_close and quote.change_pct is not None:
            high_pct = (quote.high - quote.prev_close) / quote.prev_close * 100
            limit = 10.0
            if quote.board == "创业板" or quote.board == "科创板":
                limit = 20.0
            elif quote.board == "北交所":
                limit = 30.0
            if high_pct >= limit - 0.15 and quote.change_pct < limit - 0.15:
                broken += 1
    stats["炸板家数"] = broken
    return stats


def build_search_index(universe: list[Quote]) -> list[list]:
    """构造前端搜索用的精简索引。

    两个设计选择，都是为了控制体积：

    1. **用数组而不是对象**。5500 多只股票如果用 ``{"code":...,"name":...}``
       这种带字段名的写法要 500KB 以上，用固定顺序的数组只要 200 多 KB。
       字段顺序：``[代码, 名称, 现价, 涨跌幅, 换手率, 成交额(万元)]``。
    2. **按成交额降序**。搜索「银行」这类词会命中几十只，把流动性好的排在
       前面更符合直觉；这也让前端不必再排序。

    索引只在浏览器本地过滤，不发任何请求——5500 条数组匹配是微秒级的。
    """
    rows: list[list] = []
    for quote in universe:
        if not quote.code or not quote.name:
            continue
        rows.append(
            [
                quote.code,
                quote.name,
                round(quote.price, 2) if quote.price else 0,
                round(quote.change_pct, 2) if quote.change_pct is not None else None,
                round(quote.turnover, 2) if quote.turnover is not None else None,
                int((quote.amount or 0) / 10_000),  # 元 → 万元，省一半字符
            ]
        )
    rows.sort(key=lambda row: row[5], reverse=True)
    return rows
