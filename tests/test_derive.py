from __future__ import annotations

from ashare_watch.derive import build_breadth, build_limit_stats, build_rankings, tradable
from ashare_watch.models import Quote


def make(
    code: str,
    change_pct: float,
    *,
    name: str = "测试股",
    price: float = 10.0,
    volume: float = 1_000_000,
    amount: float = 100_000_000,
    turnover: float = 2.0,
    board: str = "主板",
    limit_status: str = "",
    high: float | None = None,
    prev_close: float | None = 10.0,
) -> Quote:
    return Quote(
        code=code,
        sina="sh" + code,
        name=name,
        price=price,
        change_pct=change_pct,
        volume=volume,
        amount=amount,
        turnover=turnover,
        board=board,
        limit_status=limit_status,
        high=high if high is not None else price,
        prev_close=prev_close,
    )


def test_tradable_filters_suspended_and_new_listings():
    universe = [
        make("600519", 1.0),
        make("600520", 0.0, price=0.0),            # 停牌
        make("600521", 0.0, volume=0.0),           # 无成交
        make("600522", 300.0, name="N新股"),        # 新股首日，不受涨跌停限制
        make("600523", 50.0, name="C次新"),         # 次新股
    ]
    assert [q.code for q in tradable(universe)] == ["600519"]


def test_rankings_sort_correctly():
    universe = [
        make("600001", 5.0),
        make("600002", -3.0),
        make("600003", 12.0),
        make("600004", -8.0),
    ]
    gainers, losers, _active, _turnover = build_rankings(universe, limit=2)
    assert [q.code for q in gainers] == ["600003", "600001"]
    assert [q.code for q in losers] == ["600004", "600002"]


def test_most_active_uses_amount_not_volume():
    universe = [
        make("600001", 1.0, price=2.0, amount=20_000_000),
        make("600002", 1.0, price=500.0, amount=900_000_000),
    ]
    _g, _l, active, _t = build_rankings(universe, limit=2)
    assert active[0].code == "600002"


def test_turnover_ranking_is_a_share_specific():
    universe = [
        make("600001", 1.0, turnover=1.2),
        make("600002", 1.0, turnover=25.6),
    ]
    _g, _l, _a, turnover = build_rankings(universe, limit=2)
    assert turnover[0].code == "600002"


def test_breadth_counts_directions():
    universe = [
        make("600001", 1.0),
        make("600002", 2.0),
        make("600003", -1.0),
        make("600004", 0.0),
        make("600005", 0.0, price=0.0),   # 停牌不计入
    ]
    result = build_breadth(universe)
    assert result["advancers"] == 2
    assert result["decliners"] == 1
    assert result["unchanged"] == 1
    assert result["total"] == 4
    assert result["ratio"] == 0.5


def test_limit_stats_count_up_down_and_one_word():
    universe = [
        make("600001", 10.0, limit_status="涨停"),
        make("600002", 10.0, limit_status="一字涨停"),
        make("600003", -10.0, limit_status="跌停"),
        make("600004", 1.0),
    ]
    stats = build_limit_stats(universe)
    assert stats["涨停家数"] == 2
    assert stats["跌停家数"] == 1
    assert stats["一字涨停"] == 1


def test_broken_board_detection():
    """炸板：盘中触及涨停但收盘未封住。"""
    universe = [
        # 涨停价 11.0（10%），最高到过 11.0 但收在 10.4 → 炸板
        make("600001", 4.0, price=10.4, high=11.0, prev_close=10.0),
        # 普通上涨，没碰过涨停
        make("600002", 3.0, price=10.3, high=10.4, prev_close=10.0),
        # 已经封住涨停，不算炸板
        make("600003", 10.0, price=11.0, high=11.0, prev_close=10.0, limit_status="涨停"),
    ]
    stats = build_limit_stats(universe)
    assert stats["炸板家数"] == 1

