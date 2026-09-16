"""A 股交易规则的测试。

这些规则是 A 股看板正确性的基础：交易时段判断错了会导致刷新节奏错乱，
涨跌停幅度判断错了会把创业板和主板混为一谈。
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ashare_watch.market import (
    BEIJING,
    board_of,
    beijing_now,
    detect_limit,
    is_st,
    limit_pct,
    market_status,
)


def test_beijing_now_is_utc_plus_8():
    moment = beijing_now()
    assert moment.utcoffset().total_seconds() == 8 * 3600


@pytest.mark.parametrize(
    "hour,minute,expected,is_open",
    [
        (9, 20, "集合竞价", False),
        (9, 35, "交易中", True),
        (11, 0, "交易中", True),
        (12, 0, "午间休市", False),
        (13, 30, "交易中", True),
        (15, 30, "已收盘", False),
        (8, 0, "已收盘", False),
    ],
)
def test_market_status_sessions(hour, minute, expected, is_open):
    # 2026-09-16 是周三
    moment = datetime(2026, 9, 16, hour, minute, tzinfo=BEIJING)
    status = market_status(moment)
    assert status.status == expected
    assert status.is_open is is_open


def test_market_status_weekend_is_closed():
    saturday = datetime(2026, 9, 19, 10, 0, tzinfo=BEIJING)
    status = market_status(saturday)
    assert status.status == "休市"
    assert status.is_open is False


def test_market_status_morning_session_label():
    morning = datetime(2026, 9, 16, 10, 0, tzinfo=BEIJING)
    assert market_status(morning).session == "上午盘"
    afternoon = datetime(2026, 9, 16, 14, 0, tzinfo=BEIJING)
    assert market_status(afternoon).session == "下午盘"


def test_board_of_classifies_by_code():
    assert board_of("600519").name == "主板"
    assert board_of("000001").name == "主板"
    assert board_of("300750").name == "创业板"
    assert board_of("301029").name == "创业板"
    assert board_of("688981").name == "科创板"
    assert board_of("920298").name == "北交所"
    assert board_of("830799").name == "北交所"


def test_limit_pct_differs_by_board():
    assert limit_pct("600519") == 10.0
    assert limit_pct("300750") == 20.0
    assert limit_pct("688981") == 20.0
    assert limit_pct("920298") == 30.0
    # 主板 ST 股幅度收窄到 5%
    assert limit_pct("600519", "ST某某") == 5.0
    # 创业板 ST 仍是 20%
    assert limit_pct("300750", "ST某某") == 20.0


def test_is_st_recognises_both_forms():
    assert is_st("ST亚光") is True
    assert is_st("*ST海核") is True
    assert is_st("贵州茅台") is False


def test_detect_limit_up_with_tolerance():
    """涨跌停价四舍五入到分，实际涨幅常常是 9.97%，不能用等号判断。"""
    status = detect_limit(
        code="600519", name="贵州茅台", change_pct=9.98,
        price=11.0, open_price=10.5, high=11.0, low=10.5,
    )
    assert status == "涨停"
    # 差得远就不算
    assert detect_limit(
        code="600519", name="贵州茅台", change_pct=7.5,
        price=10.75, open_price=10.2, high=10.8, low=10.1,
    ) == ""


def test_detect_limit_down_for_chinext():
    status = detect_limit(
        code="300750", name="宁德时代", change_pct=-19.95,
        price=80.0, open_price=90.0, high=90.0, low=80.0,
    )
    assert status == "跌停"


def test_detect_one_word_board():
    """一字板：开=高=低=收，全天没有波动，和普通涨停含义完全不同。"""
    status = detect_limit(
        code="600519", name="贵州茅台", change_pct=10.02,
        price=11.0, open_price=11.0, high=11.0, low=11.0,
    )
    assert status == "一字涨停"


def test_detect_limit_ignores_missing_data():
    assert detect_limit(
        code="600519", name="贵州茅台", change_pct=None,
        price=None, open_price=None, high=None, low=None,
    ) == ""

