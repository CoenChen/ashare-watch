"""不联网的解析测试：把真实响应片段喂给解析逻辑。

这些 payload 摘自实测得到的真实响应（字段名与格式完全一致），
所以既能在没有网络的环境下跑，又能真正验证解析正确性。
"""

from __future__ import annotations

from ashare_watch.client import SinaClient
from ashare_watch.config import Settings

SINA_QUOTE_TEXT = (
    'var hq_str_sh600519="贵州茅台,1273.930,1272.750,1257.050,1274.980,1254.100,'
    '1257.020,1257.320,1790162,2258702422.000,2026-09-16,11:30:00,00,";\n'
    'var hq_str_sh000001="上证指数,3861.7457,3864.2794,3886.4810,3887.2940,3842.7211,'
    '0,0,292997691,552814174810,2026-09-16,11:35:57,00,";\n'
)

UNIVERSE_JSON = (
    '[{"symbol":"bj920298","code":"920298","name":"N腾信","trade":"61.260",'
    '"pricechange":25.48,"changepercent":71.213,"settlement":"35.780","open":"62.000",'
    '"high":"65.000","low":"54.010","volume":11622250,"amount":670510509,'
    '"turnoverratio":75.96,"per":19.6,"pb":3.4,"mktcap":477828,"nmc":93727.8},'
    '{"symbol":"sh600519","code":"600519","name":"贵州茅台","trade":"1257.050",'
    '"pricechange":-15.70,"changepercent":-1.233,"settlement":"1272.750","open":"1273.930",'
    '"high":"1274.980","low":"1254.100","volume":1790162,"amount":2258702422,'
    '"turnoverratio":0.14,"per":21.5,"pb":7.1,"mktcap":157900000,"nmc":157900000}]'
)

SECTOR_JS = (
    'var S_Finance_bankuai_sinaindustry = {'
    '"new_blhy":"new_blhy,玻璃行业,19,17.80,0.15,0.8798,455242699,12066951496,'
    'sh600552,2.988,17.580,0.510,凯盛科技",'
    '"new_cbzz":"new_cbzz,船舶制造,8,14.62,-0.19,-1.2829,191870261,3470698026,'
    'sz300123,3.812,4.630,0.170,ST亚光"};'
)

KLINE_JSON = (
    '[{"day":"2026-09-14","open":"3864.279","high":"3891.220","low":"3855.100",'
    '"close":"3886.481","volume":"292997691"},'
    '{"day":"2026-09-15","open":"3887.000","high":"3900.500","low":"3870.000",'
    '"close":"3892.330","volume":"301234567"}]'
)


def client_with(payload: bytes) -> SinaClient:
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    client._request = lambda host, path, params=None: payload  # type: ignore[assignment]
    return client


def test_parse_batch_quotes_marks_board_and_direction():
    client = client_with(SINA_QUOTE_TEXT.encode("gbk"))
    quotes = client.quotes(["sh600519", "sh000001"])
    assert len(quotes) == 2
    by_sina = {q.sina: q for q in quotes}
    maotai = by_sina["sh600519"]
    assert maotai.code == "600519"
    assert maotai.name == "贵州茅台"
    assert maotai.price == 1257.05
    assert maotai.direction == "down"
    assert maotai.board == "主板"
    # 指数不应有涨跌停标记
    index = by_sina["sh000001"]
    assert index.limit_status == ""


def test_parse_universe_page_fills_all_fields():
    client = client_with(UNIVERSE_JSON.encode("gbk"))
    rows = client.universe_page(1)
    assert len(rows) == 2
    maotai = next(q for q in rows if q.code == "600519")
    assert maotai.name == "贵州茅台"
    assert maotai.turnover == 0.14
    assert maotai.pe == 21.5
    # 新浪的市值单位是万元，解析时要换算成元
    assert maotai.market_cap == 157_900_000 * 10_000
    # 新股 N 开头会被打上标记（过滤发生在 derive 层）
    new_stock = next(q for q in rows if q.code == "920298")
    assert new_stock.board == "北交所"


def test_limit_detection_on_universe_rows():
    payload = (
        '[{"code":"600001","name":"测试股","trade":"11.000","pricechange":1.0,'
        '"changepercent":10.0,"settlement":"10.000","open":"11.000","high":"11.000",'
        '"low":"11.000","volume":1000000,"amount":11000000,"turnoverratio":1.0,'
        '"per":10,"pb":1,"mktcap":100000,"nmc":100000}]'
    )
    client = client_with(payload.encode("gbk"))
    rows = client.universe_page(1)
    assert rows[0].limit_status == "一字涨停"


def test_parse_sectors_ja_payload():
    client = client_with(SECTOR_JS.encode("gbk"))
    sectors = client.sectors()
    assert len(sectors) == 2
    # 按涨跌幅降序
    assert sectors[0].name == "玻璃行业"
    assert sectors[0].change_pct == 0.8798
    assert sectors[0].company_count == 19
    assert sectors[0].leader_name == "凯盛科技"
    assert sectors[1].name == "船舶制造"
    assert sectors[1].change_pct < 0


def test_parse_index_history():
    client = client_with(KLINE_JSON.encode("utf-8"))
    rows = client.index_history("sh000001", days=10)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-09-14"
    assert rows[0]["close"] == 3886.481


def test_caches_avoid_repeated_requests():
    client = client_with(SECTOR_JS.encode("gbk"))
    calls = {"n": 0}
    original = client._request

    def counting(host, path, params=None):
        calls["n"] += 1
        return original(host, path, params)

    client._request = counting  # type: ignore[assignment]
    client.sectors()
    client.sectors()
    assert calls["n"] == 1, "第二次应命中缓存"


def test_failed_request_returns_empty_not_exception():
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    client._request = lambda host, path, params=None: None  # type: ignore[assignment]
    assert client.quotes(["sh600519"]) == []
    assert client.sectors() == []
    assert client.index_history("sh000001") == []
