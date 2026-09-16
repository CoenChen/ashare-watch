from __future__ import annotations

from ashare_watch.structure import (
    decode_gbk,
    format_money,
    format_shares,
    is_index_symbol,
    market_label,
    parse_js_object,
    parse_json_array,
    parse_number,
    parse_percent,
    parse_sina_quotes,
    quote_fields,
    short_code,
    to_sina_symbol,
)


def test_to_sina_symbol_maps_markets():
    assert to_sina_symbol("600519") == "sh600519"
    assert to_sina_symbol("688981") == "sh688981"
    assert to_sina_symbol("000001") == "sz000001"
    assert to_sina_symbol("300750") == "sz300750"
    assert to_sina_symbol("920298") == "bj920298"
    # 已经是新浪格式就原样返回
    assert to_sina_symbol("sh000001") == "sh000001"


def test_index_detection_needs_market_prefix():
    """sh000001 是上证指数，sz000001 是平安银行——只看 6 位数字会弄混。"""
    assert is_index_symbol("sh000001") is True
    assert is_index_symbol("sz399001") is True
    assert is_index_symbol("bj899050") is True
    assert is_index_symbol("sz000001") is False
    assert is_index_symbol("sh600519") is False


def test_short_code_and_market_label():
    assert short_code("sh600519") == "600519"
    assert market_label("sh600519") == "沪"
    assert market_label("sz300750") == "深"


def test_parse_number_and_percent():
    assert parse_number("1257.050") == 1257.050
    assert parse_number("--") is None
    assert parse_number("") is None
    assert parse_percent("-3.809") == -3.809
    assert parse_percent("5.2%") == 5.2
    assert parse_percent("+5.2%") == 5.2


def test_parse_sina_quotes_extracts_lines():
    text = (
        'var hq_str_sh600519="贵州茅台,1273.930,1272.750,1257.050,1274.980,1254.100,'
        '1257.020,1257.320,1790162,2258702422.000,2026-09-16,11:30:00,00,";\n'
        'var hq_str_sh000001="上证指数,3861.7457,3864.2794,3886.4810,3887.2940,3842.7211,'
        '0,0,292997691,552814174810,2026-09-16,11:35:57,00,";'
    )
    parsed = parse_sina_quotes(text)
    assert set(parsed) == {"sh600519", "sh000001"}
    assert len(parsed["sh600519"]) > 10


def test_quote_fields_computes_change_and_timestamp():
    fields = (
        "贵州茅台,1273.930,1272.750,1257.050,1274.980,1254.100,1257.020,1257.320,"
        "1790162,2258702422.000,500,1257.020,2026-09-16,11:30:00,00,"
    ).split(",")
    data = quote_fields(fields)
    assert data["name"] == "贵州茅台"
    assert data["price"] == 1257.05
    assert data["prev_close"] == 1272.75
    assert data["change"] == round(1257.05 - 1272.75, 4)
    assert round(data["change_pct"], 2) == -1.23
    assert data["timestamp"] == "2026-09-16 11:30:00"
    assert data["volume"] == 1790162.0


def test_parse_json_array_handles_sina_payload():
    text = '[{"code":"600519","name":"贵州茅台","trade":"1257.050"}]'
    rows = parse_json_array(text)
    assert rows[0]["code"] == "600519"
    assert rows[0]["trade"] == "1257.050"
    assert parse_json_array("not json") == []


def test_parse_js_object_extracts_sector_payload():
    text = (
        'var S_Finance_bankuai_sinaindustry = {"new_blhy":"new_blhy,玻璃行业,19,17.80,'
        '0.15,0.8798,455242699,12066951496,sh600552,2.988,17.580,0.510,凯盛科技"};'
    )
    payload = parse_js_object(text)
    assert "new_blhy" in payload
    parts = payload["new_blhy"].split(",")
    assert parts[1] == "玻璃行业"
    assert parts[2] == "19"


def test_decode_gbk_falls_back_instead_of_raising():
    raw = "贵州茅台".encode("gbk")
    assert decode_gbk(raw) == "贵州茅台"
    assert isinstance(decode_gbk(b"\xff\xfe\x00bad"), str)


def test_format_helpers_use_chinese_units():
    assert format_money(1_234_567_890_000) == "1.23 万亿"
    assert format_money(3_500_000_000) == "35.00 亿"
    assert format_money(None) == "—"
    # 成交量按「手」显示（1 手 = 100 股）
    assert format_shares(1_000_000) == "1.0 万手"
