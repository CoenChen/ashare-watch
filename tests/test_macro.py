"""环球市场（黄金 / 原油 / 基本金属 / 国内期货 / 外汇）的解析测试。

这里的 payload 是**实测抓到的真实返回**，字段位置完全一致。
新浪对这几类品种用了四套不同的布局，而且都是按下标取的，
所以必须逐套锁死——不然哪天改错一个下标，页面上的数字会悄悄变错。
"""

from __future__ import annotations

from ashare_watch.client import SinaClient
from ashare_watch.config import (
    MACRO_GROUPS,
    MACRO_CHUNK_SIZE,
    MACRO_UNITS,
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

# 实测返回：国内期货（上期所沪金主力）。注意第 5 位「昨收盘」恒为 0.000，
# 基准价要看第 10 位「昨结算」。
NF_GOLD = (
    "沪金连续,000645,948.200,949.240,943.360,0.000,946.720,946.840,946.760,"
    "0.000,937.200,1,1,188296.000,46605,上期所,黄金,2026-09-18,1,,"
).split(",") + [""] * 25

SINA_TEXT = (
    'var hq_str_hf_XAU="' + ",".join(HF_GOLD) + '";\n'
    'var hq_str_hf_CL="' + ",".join(HF_OIL) + '";\n'
    'var hq_str_fx_susdcny="' + ",".join(FX_USDCNY) + '";\n'
    'var hq_str_DINIW="' + ",".join(PLAIN_DINIW) + '";\n'
    'var hq_str_nf_AU0="' + ",".join(NF_GOLD) + '";\n'
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


def test_parse_domestic_futures_layout():
    """国内期货取第 8 位最新价、第 10 位昨结算。

    这条断言是防回归的重点：曾经用简化布局去套 ``nf_``，把第 3 位「今日最高」
    当成了昨收，沪金的涨跌幅直接从 +1% 变成 -0.3%。
    """
    data = macro_fields("nf_AU0", NF_GOLD)
    assert data["price"] == 946.76
    assert data["prev_close"] == 937.20      # 昨结算，不是 949.24（今日最高）
    assert data["high"] == 949.24
    assert data["low"] == 943.36
    assert data["open"] == 948.20
    assert data["time"] == "00:06:45"        # 000645 补上分隔符
    assert data["date"] == "2026-09-18"


def test_domestic_futures_direction_is_up():
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    client._request = lambda host, path, params=None: SINA_TEXT.encode("gbk")  # type: ignore[assignment]
    quotes = client.macro_quotes(["nf_AU0"])
    assert len(quotes) == 1
    gold = quotes[0]
    assert gold.direction == "up"
    assert round(gold.change, 2) == 9.56             # 946.76 - 937.20
    assert round(gold.change_pct, 2) == 1.02
    assert gold.unit == "元/克"
    assert gold.group == "国内贵金属"


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
    assert set(MACRO_GROUPS) == {
        "贵金属", "国内贵金属", "能源", "基本金属", "黑色系", "化工", "农产品",
        "海外股指", "外汇", "数字货币",
    }


def test_macro_covers_pm_and_fx_broadly():
    """贵金属和外汇要覆盖足够多的品种——这两类是用户明确要求扩充的。"""
    pm = {name for _, name in MACRO_GROUPS["贵金属"]}
    assert {"伦敦金", "纽约黄金", "伦敦银", "纽约白银", "伦敦铂金", "伦敦钯金"} <= pm
    # 国内金价：A 股黄金股（山东黄金、中金黄金）跟的是这个，不是伦敦金
    assert {"沪金主力", "沪银主力"} <= {name for _, name in MACRO_GROUPS["国内贵金属"]}

    fx = {name for _, name in MACRO_GROUPS["外汇"]}
    assert {
        "美元指数", "美元人民币", "离岸人民币", "欧元美元", "美元日元",
        "英镑美元", "澳元美元", "美元港元", "美元加元", "美元瑞郎",
        "纽元美元", "欧元英镑", "欧元日元", "英镑日元", "美元新加坡元", "美元韩元",
    } <= fx
    assert len(fx) >= 16


def test_macro_covers_index_futures_for_overnight_sentiment():
    """隔夜外盘是 A 股开盘前最直接的情绪参考，必须覆盖。"""
    index_names = {name for _, name in MACRO_GROUPS["海外股指"]}
    assert {"标普500期货", "纳指100期货", "道指期货", "恒指期货", "富时A50期货"} <= index_names


def test_macro_covers_domestic_commodity_chains():
    """国内期货要覆盖几条主要的产业链，而不是只放一两个装样子。"""
    assert {"螺纹钢", "铁矿石", "焦煤", "焦炭"} <= {n for _, n in MACRO_GROUPS["黑色系"]}
    assert {"PTA", "甲醇", "纯碱"} <= {n for _, n in MACRO_GROUPS["化工"]}
    assert {"豆粕", "郑棉", "白糖"} <= {n for _, n in MACRO_GROUPS["农产品"]}


def test_every_macro_symbol_has_a_unit_or_is_an_fx_pair():
    """贵金属/能源/基本金属必须标注计价单位，否则看不出量级是否正常。
    汇率本身没有单位，允许为空。"""
    for group in ("贵金属", "国内贵金属", "能源", "基本金属", "黑色系",
                  "化工", "农产品", "海外股指", "数字货币"):
        for code, name in MACRO_GROUPS[group]:
            assert MACRO_UNITS.get(code), f"{name}({code}) 缺少计价单位"


def test_macro_batches_stay_short_enough():
    """每一批的 list= 都不能太长。

    新浪的 ``list=`` 拼在 URL 里，五十多个代码压成一条超长 URL 有被截断的风险，
    所以客户端会按 MACRO_CHUNK_SIZE 拆分。这条测试保证拆完之后每一批都是短 URL。
    """
    symbols = default_macro_symbols()
    assert len(symbols) <= 60
    for start in range(0, len(symbols), MACRO_CHUNK_SIZE):
        batch = symbols[start : start + MACRO_CHUNK_SIZE]
        assert len(",".join(batch)) < 400, "查询串太长，新浪的 list= 有长度限制"


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


def test_macro_quotes_splits_long_lists_into_short_batches():
    """品种多起来以后要自动分批，不能拼出一条超长 URL。"""
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    seen: list[str] = []

    def fake_request(host, path, params=None):
        seen.append(path)
        return None

    client._request = fake_request  # type: ignore[assignment]
    client.macro_quotes([f"hf_T{i}" for i in range(95)])

    assert len(seen) == 3                     # 95 个按 40 一批切成 3 批
    assert all(len(path) < 400 for path in seen)
    assert all(path.startswith("/list=") for path in seen)


def test_macro_quotes_merges_every_batch_and_keeps_order():
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))

    def fake_request(host, path, params=None):
        batch = path[len("/list=") :].split(",")
        text = "\n".join(
            f'var hq_str_{symbol}="' + ",".join(HF_GOLD) + '";' for symbol in batch
        )
        return text.encode("gbk")

    client._request = fake_request  # type: ignore[assignment]
    symbols = ["hf_XAU"] + [f"hf_T{i}" for i in range(50)]
    quotes = client.macro_quotes(symbols)

    assert [q.symbol for q in quotes] == symbols, "返回顺序要跟配置顺序一致"
