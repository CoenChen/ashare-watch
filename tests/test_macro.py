"""环球市场（黄金 / 原油 / 外汇 / 基本金属）的解析测试。

这里的 payload 是**实测抓到的真实返回**，字段位置完全一致。
新浪对这三类品种用了三套不同的布局，而且都是按下标取的，
所以必须逐套锁死——不然哪天改错一个下标，页面上的数字会悄悄变错。
"""

from __future__ import annotations

from ashare_watch.client import SinaClient
from ashare_watch.config import (
    MACRO_GROUPS,
    Settings,
    default_macro_symbols,
    macro_group_of,
    macro_name_of,
)
from ashare_watch.structure import digits_for, macro_fields

# 实测返回：外盘期货（现价,买价,卖价,开盘,最高,最低,时间,昨收,今开,...,日期,名称）
HF_GOLD = (
    "4362.56,4263.940,4362.56,4362.91,4381.14,4257.40,23:16:00,4263.94,4260.49,"
    "0,0,0,2026-09-17,伦敦金（现货黄金）"
).split(",")

HF_OIL = (
    "96.429,,96.290,96.300,97.730,94.640,23:17:15,97.510,97.530,"
    "0,3,6,2026-09-17,纽约原油,0"
).split(",")

# 实测返回：外汇即期（自带涨跌幅与涨跌额）
FX_USDCNY = (
    "23:16:41,6.7055000000,6.7075000000,6.7121000000,167.0000000000,6.7078000000,"
    "6.7118000000,6.6951000000,6.7065000000,在岸人民币,-0.0834,-0.0056,0.0167,"
    "此行情由新浪财经计算得出,0.0000,0.0000,,2026-09-17"
).split(",")

# 实测返回：美元指数走的是简化布局，没有涨跌幅字段
PLAIN_DINIW = (
    "23:17:07,100.1634,100.1634,100.3293,3461,100.3086,100.3676,100.0215,"
    "100.1634,美元指数,2026-09-17"
).split(",")

SINA_TEXT = (
    'var hq_str_hf_XAU="' + ",".join(HF_GOLD) + '";\n'
    'var hq_str_hf_CL="' + ",".join(HF_OIL) + '";\n'
    'var hq_str_fx_susdcny="' + ",".join(FX_USDCNY) + '";\n'
    'var hq_str_DINIW="' + ",".join(PLAIN_DINIW) + '";\n'
)


def test_parse_overseas_futures_layout():
    data = macro_fields("hf_XAU", HF_GOLD)
    assert data["price"] == 4362.56
    assert data["prev_close"] == 4263.94
    assert data["high"] == 4381.14      # 必须大于现价
    assert data["low"] == 4257.40       # 必须小于现价
    assert data["open"] == 4260.49
    assert data["time"] == "23:16:00"
    assert data["date"] == "2026-09-17"


def test_parse_overseas_futures_with_empty_bid_field():
    """WTI 原油的买价字段是空的，解析不能因此错位。"""
    data = macro_fields("hf_CL", HF_OIL)
    assert data["price"] == 96.429
    assert data["prev_close"] == 97.510
    assert data["high"] == 97.730
    assert data["low"] == 94.640


def test_parse_fx_layout_uses_provided_change():
    data = macro_fields("fx_susdcny", FX_USDCNY)
    assert data["price"] == 6.7065
    assert data["prev_close"] == 6.7121
    assert data["change"] == -0.0056
    assert data["change_pct"] == -0.0834
    assert data["name"] == "在岸人民币"
    assert data["date"] == "2026-09-17"


def test_parse_plain_layout_has_no_change_fields():
    """美元指数不提供涨跌幅，需要通过昨收自己算。"""
    data = macro_fields("DINIW", PLAIN_DINIW)
    assert data["price"] == 100.1634
    assert data["prev_close"] == 100.3293
    assert data["change"] is None
    assert data["change_pct"] is None
    assert data["date"] == "2026-09-17"


def test_digits_by_magnitude():
    """汇率要 4 位小数才有信息量，黄金 2 位就够。"""
    assert digits_for(6.7065) == 4
    assert digits_for(1.1486) == 4
    assert digits_for(155.80) == 2
    assert digits_for(4362.56) == 2
    assert digits_for(100.1634) == 2
    assert digits_for(None) == 2


def test_macro_config_is_consistent():
    symbols = default_macro_symbols()
    assert len(symbols) == len(set(symbols)), "品种代码不能重复"
    for code, name in [item for group in MACRO_GROUPS.values() for item in group]:
        assert macro_name_of(code) == name
        assert macro_group_of(code) in MACRO_GROUPS
    assert set(MACRO_GROUPS) == {"贵金属", "能源", "基本金属", "外汇"}


def test_macro_group_lookup_covers_every_symbol():
    for group, items in MACRO_GROUPS.items():
        for code, _name in items:
            assert macro_group_of(code) == group


def test_client_builds_macro_quotes():
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    client._request = lambda host, path, params=None: SINA_TEXT.encode("gbk")  # type: ignore[assignment]
    quotes = client.macro_quotes(["hf_XAU", "hf_CL", "fx_susdcny", "DINIW"])
    assert len(quotes) == 4
    by_symbol = {q.symbol: q for q in quotes}

    gold = by_symbol["hf_XAU"]
    assert gold.name == "伦敦金" and gold.group == "贵金属"
    assert gold.unit == "美元/盎司"
    assert round(gold.change, 2) == 98.62          # 4362.56 - 4263.94
    assert round(gold.change_pct, 2) == 2.31
    assert gold.direction == "up"

    oil = by_symbol["hf_CL"]
    assert oil.direction == "down"                  # 96.429 < 97.510
    assert oil.unit == "美元/桶"

    cny = by_symbol["fx_susdcny"]
    assert cny.digits == 4
    assert cny.direction == "down"

    dxy = by_symbol["DINIW"]
    assert dxy.unit == "点"
    # 简化布局没有涨跌幅，客户端要自己从昨收算出来
    assert dxy.change_pct is not None
    assert round(dxy.change_pct, 2) == -0.17


def test_macro_missing_symbol_is_skipped():
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    client._request = lambda host, path, params=None: SINA_TEXT.encode("gbk")  # type: ignore[assignment]
    quotes = client.macro_quotes(["hf_XAU", "fx_snonexist"])
    assert [q.symbol for q in quotes] == ["hf_XAU"]


def test_macro_request_failure_returns_empty():
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    client._request = lambda host, path, params=None: None  # type: ignore[assignment]
    assert client.macro_quotes() == []

