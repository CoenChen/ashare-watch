"""个股详情的解析与接口测试。

详情是「点开时才抓」的：全市场 5500 只不可能每只都预抓一份 K 线，
但单只股票只要 4 个请求。这里锁住两件事——五档盘口别解析错位，
以及接口在抓不到数据时也要老老实实返回空结构而不是报错。
"""

from __future__ import annotations

import urllib.error
import urllib.parse

from ashare_watch.client import SinaClient
from ashare_watch.config import Settings
from ashare_watch.structure import orderbook_fields

from conftest import get_json

# 实测返回：贵州茅台（个股行情比指数多出 10–29 位的五档）
STOCK_FIELDS = (
    "贵州茅台,1262.990,1266.980,1256.470,1265.880,1256.100,"
    "1256.410,1256.470,1305373,1645057760.000,"
    "400,1256.410,100,1256.400,100,1256.380,300,1256.350,100,1256.320,"
    "2500,1256.470,400,1256.600,400,1256.610,800,1256.630,100,1256.640,"
    "2026-09-18,13:07:48,00,"
).split(",")


def test_orderbook_parses_five_levels_each_side():
    book = orderbook_fields(STOCK_FIELDS)
    assert book["bids"] == [
        [1256.410, 400.0],
        [1256.400, 100.0],
        [1256.380, 100.0],
        [1256.350, 300.0],
        [1256.320, 100.0],
    ]
    assert book["asks"] == [
        [1256.470, 2500.0],
        [1256.600, 400.0],
        [1256.610, 400.0],
        [1256.630, 800.0],
        [1256.640, 100.0],
    ]
    # 买一价必须低于卖一价，否则就是取错了位置
    assert book["bids"][0][0] < book["asks"][0][0]


def test_orderbook_is_empty_for_indexes():
    """指数没有五档，这一段全是 0，不能被当成有效盘口。"""
    fields = (
        "上证指数,3886.4800,3891.5988,3875.6048,3898.8410,3866.8900,"
        "0,0,45129248400,530655044000," + "0," * 20 + "2026-09-17,15:30:00,00,"
    ).split(",")
    book = orderbook_fields(fields)
    assert book["bids"] == []
    assert book["asks"] == []


def test_orderbook_tolerates_short_payload():
    assert orderbook_fields(["名称", "1", "2"]) == {"bids": [], "asks": []}


def test_stock_detail_returns_empty_shape_without_network():
    """抓不到数据时也要返回完整结构，前端才不用到处判空。"""
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))
    client._request = lambda host, path, params=None: None  # type: ignore[assignment]
    detail = client.stock_detail("sh600519")

    assert detail["code"] == "600519"
    assert detail["quote"] is None
    assert detail["orderbook"] == {"bids": [], "asks": []}
    assert detail["daily"] == [] and detail["intraday"] == [] and detail["moneyflow"] == []


def test_stock_detail_builds_quote_and_orderbook():
    """行情那一批要同时产出 Quote 和五档——它们是同一个请求的返回。"""
    client = SinaClient(Settings(data_dir="/tmp/ashare-watch-test"))

    text = 'var hq_str_sh600519="' + ",".join(STOCK_FIELDS) + '";\n'

    def fake_request(host, path, params=None):
        if path.startswith("/list="):
            return text.encode("gbk")
        return None

    client._request = fake_request  # type: ignore[assignment]
    detail = client.stock_detail("sh600519")

    assert detail["quote"]["name"] == "贵州茅台"
    assert detail["quote"]["price"] == 1256.47
    assert len(detail["orderbook"]["bids"]) == 5
    assert len(detail["orderbook"]["asks"]) == 5


def test_detail_endpoint_rejects_bad_code(live_server):
    """代码会被拼进上游请求路径，所以必须在入口卡死格式。"""
    base, _collector = live_server
    for bad in ("", "abc", "600519,sz000001", "../etc", "12345", "6005199"):
        try:
            get_json(f"{base}/api/stock?code={urllib.parse.quote(bad)}")
            raise AssertionError(f"{bad!r} 应该被拒绝")
        except urllib.error.HTTPError as error:
            assert error.code == 400, bad


def test_detail_endpoint_returns_empty_shape_offline(live_server):
    base, _collector = live_server
    data = get_json(f"{base}/api/stock?code=600519")
    assert data["code"] == "600519"
    assert "orderbook" in data and "daily" in data
