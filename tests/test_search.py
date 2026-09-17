"""搜索功能测试。

搜索本身跑在浏览器里（纯本地数组过滤），但索引的**构造**在 Python 这边，
字段顺序和排序规则一旦改错，前端会静默显示错误的数据——所以这里要锁死。
"""

from __future__ import annotations

from ashare_watch.config import Settings
from ashare_watch.derive import build_search_index
from ashare_watch.models import Quote
from ashare_watch.render import build_standalone_html


def make(code: str, name: str, price: float, pct: float, turnover: float, amount: float) -> Quote:
    return Quote(
        code=code,
        name=name,
        price=price,
        change_pct=pct,
        turnover=turnover,
        amount=amount,
        volume=1_000_000,
        board="主板",
    )


def test_search_index_field_order_and_units():
    """字段顺序是前端按数组下标取的，改顺序等于改契约。"""
    rows = build_search_index([make("600519", "贵州茅台", 1258.0, -1.16, 0.14, 2_258_702_422)])
    assert rows == [["600519", "贵州茅台", 1258.0, -1.16, 0.14, 225870]]
    # 成交额单位是万元：225870 万元 = 22.587 亿
    assert rows[0][5] == 225870


def test_search_index_sorted_by_amount_desc():
    """同分时按成交额排，所以索引本身要按成交额降序。"""
    rows = build_search_index(
        [
            make("600001", "小盘股", 10.0, 1.0, 1.0, 20_000_000),
            make("600002", "大盘股", 100.0, 1.0, 1.0, 900_000_000),
            make("600003", "中盘股", 50.0, 1.0, 1.0, 200_000_000),
        ]
    )
    assert [row[0] for row in rows] == ["600002", "600003", "600001"]


def test_search_index_skips_incomplete_rows():
    universe = [
        make("600519", "贵州茅台", 1258.0, -1.16, 0.14, 1e9),
        Quote(code="", name="没有代码"),
        Quote(code="600001", name=""),
    ]
    assert len(build_search_index(universe)) == 1


def test_search_index_handles_missing_values():
    """停牌股没有价格，导出的索引里字段可能是 None，不能崩。"""
    rows = build_search_index([Quote(code="600001", name="停牌股")])
    assert rows[0][2] == 0        # 价格缺省为 0
    assert rows[0][3] is None     # 涨跌幅保留 None，前端显示「—」
    assert rows[0][5] == 0


def test_standalone_html_inlines_search_index():
    snapshot = {
        "fetched_at": "2026-09-17T15:30:00+08:00",
        "market": {"status": "已收盘"},
        "indexes": [], "watchlist": [], "gainers": [], "losers": [],
        "most_active": [], "turnover_leaders": [], "sectors": [], "macro": [],
        "breadth": {}, "limits": {}, "coverage": {}, "index_history": [],
        "warnings": [], "sources": [],
    }
    rows = [["600519", "贵州茅台", 1258.0, -1.16, 0.14, 225870]]
    html = build_standalone_html(snapshot, search_index=rows)
    assert "window.__SEARCH_INDEX__" in html
    assert '"贵州茅台"' in html


def test_standalone_html_without_search_index_still_works():
    """没传索引时不能报错，只是搜索不可用。"""
    snapshot = {"fetched_at": "", "market": {}, "indexes": [], "watchlist": [],
                "gainers": [], "losers": [], "most_active": [], "turnover_leaders": [],
                "sectors": [], "macro": [], "breadth": {}, "limits": {},
                "coverage": {}, "index_history": [], "warnings": [], "sources": []}
    html = build_standalone_html(snapshot)
    assert "window.__SNAPSHOT__" in html
    # 注意不能简单断言变量名不存在——内联的 app.js 源码里本来就会出现它。
    # 这里要检查的是「赋值注入」有没有发生。
    assert "window.__SEARCH_INDEX__ =" not in html


def test_search_index_escapes_script_tag():
    """索引里如果出现 </script> 会提前闭合脚本标签，必须转义。"""
    rows = [["600001", "</script><script>alert(1)</script>", 1.0, 0.0, 0.0, 0]]
    html = build_standalone_html({"fetched_at": ""}, search_index=rows)
    assert "</script><script>alert(1)" not in html


def test_refresh_defaults_are_measured_values():
    """刷新参数是实测出来的，别被随手改小。"""
    settings = Settings(data_dir="/tmp/ashare-watch-test")
    assert settings.refresh_seconds == 15
    assert settings.universe_ttl == 240
    # 采集本身要 6.4 秒，间隔下限必须拦住更小的值
    assert settings.min_refresh_seconds >= 2
