from __future__ import annotations

from pathlib import Path

from ashare_watch.config import Settings
from ashare_watch.render import build_standalone_html, export_snapshot
from ashare_watch.store import SnapshotStore

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "ashare_watch" / "static"


def sample_snapshot(fetched_at: str = "2026-09-16T14:05:00+08:00") -> dict:
    return {
        "fetched_at": fetched_at,
        "generated_ms": 3000.0,
        "market": {"status": "交易中", "is_open": True, "session": "下午盘"},
        "indexes": [{"code": "000001", "sina": "sh000001", "name": "上证指数", "price": 3886.48}],
        "watchlist": [],
        "gainers": [],
        "losers": [],
        "most_active": [],
        "turnover_leaders": [],
        "sectors": [],
        "breadth": {"advancers": 2000, "decliners": 3000, "unchanged": 500, "total": 5500},
        "limits": {"涨停家数": 40, "跌停家数": 5},
        "coverage": {"universe": 5500},
        "index_history": [],
        "warnings": [],
        "sources": ["hq.sinajs.cn"],
    }


def test_snapshot_roundtrip(tmp_path):
    store = SnapshotStore(tmp_path / "m.sqlite3")
    store.save_snapshot(sample_snapshot())
    latest = store.latest_snapshot()
    assert latest is not None
    assert latest["market"]["status"] == "交易中"
    assert latest["limits"]["涨停家数"] == 40


def test_latest_returns_most_recent(tmp_path):
    store = SnapshotStore(tmp_path / "m.sqlite3")
    store.save_snapshot(sample_snapshot("2026-09-16T10:00:00+08:00"))
    store.save_snapshot(sample_snapshot("2026-09-16T14:00:00+08:00"))
    assert store.latest_snapshot()["fetched_at"] == "2026-09-16T14:00:00+08:00"


def test_latest_complete_snapshot_skips_a_hollow_one(tmp_path):
    """抓取"成功"但全市场为空时，导出要退回上一份完整的。

    这种情况真实发生过：接口临时限流，56 页里大部分返回 456，
    快照照样存下来，只是榜单和涨跌停统计全空。
    """
    store = SnapshotStore(tmp_path / "m.sqlite3")
    good = sample_snapshot("2026-09-16T13:00:00+08:00")
    good["coverage"] = {"universe": 5564}
    store.save_snapshot(good)
    hollow = sample_snapshot("2026-09-16T14:00:00+08:00")
    hollow["coverage"] = {"universe": 0}
    store.save_snapshot(hollow)

    assert store.latest_snapshot()["fetched_at"] == "2026-09-16T14:00:00+08:00"
    assert store.latest_complete_snapshot()["fetched_at"] == "2026-09-16T13:00:00+08:00"


def test_latest_complete_snapshot_returns_none_when_everything_is_hollow(tmp_path):
    store = SnapshotStore(tmp_path / "m.sqlite3")
    hollow = sample_snapshot()
    hollow["coverage"] = {"universe": 0}
    store.save_snapshot(hollow)
    assert store.latest_complete_snapshot() is None


def test_collection_log_records_failures(tmp_path):
    store = SnapshotStore(tmp_path / "m.sqlite3")
    store.log_run(
        started_at="2026-09-16T10:00:00+08:00",
        finished_at="2026-09-16T10:00:03+08:00",
        status="partial",
        duration_ms=3000.0,
        requests=58,
        failures=2,
        market_status="交易中",
        message="自选股数据缺失：600519",
    )
    runs = store.recent_runs(1)
    assert runs[0]["status"] == "partial"
    assert runs[0]["failures"] == 2
    assert "600519" in runs[0]["message"]


def test_count_reports_both_tables(tmp_path):
    store = SnapshotStore(tmp_path / "m.sqlite3")
    store.save_snapshot(sample_snapshot())
    store.log_run(
        started_at="a", finished_at="b", status="ok",
        duration_ms=1.0, requests=1, failures=0,
    )
    assert store.count() == {"snapshots": 1, "runs": 1}


def test_standalone_html_inlines_everything():
    html = build_standalone_html(sample_snapshot())
    assert "/static/styles.css" not in html
    assert "/static/app.js" not in html
    assert "<style>" in html
    assert "window.__SNAPSHOT__" in html
    assert "renderLimits" in html


def test_standalone_html_keeps_assets_verbatim():
    """内联进去的 JS / CSS 必须和源文件完全一致。

    这里曾经踩过一个很隐蔽的坑：``re.sub`` 的替换内容如果按字符串传，
    里面的反斜杠会被当转义处理。JS 里只要有 ``\\d``（正则里到处都是），
    轻则 ``bad escape`` 直接报错，重则悄悄把代码改坏而看不出来。
    """
    html = build_standalone_html(sample_snapshot())
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    styles = (STATIC_DIR / "styles.css").read_text(encoding="utf-8")
    assert "\\" in app_js, "app.js 里应该存在反斜杠，否则这条测试没有意义"
    assert app_js in html
    assert styles in html


def test_standalone_html_uses_red_for_gain():
    """红涨绿跌：这是 A 股看板的正确性底线，不能照搬美股的配色。"""
    html = build_standalone_html(sample_snapshot())
    assert "--up: #ef4444" in html, "涨幅色必须是红色"
    assert "--down: #22c55e" in html, "跌幅色必须是绿色"


def test_script_closing_tag_is_escaped():
    snapshot = sample_snapshot()
    snapshot["warnings"] = ["危险 </script><script>alert(1)</script>"]
    html = build_standalone_html(snapshot)
    assert "</script><script>alert(1)" not in html
    assert "<\\/script>" in html


def test_export_writes_file(tmp_path):
    settings = Settings(data_dir=tmp_path / "data")
    target = export_snapshot(sample_snapshot(), settings)
    assert target.exists()
    assert target.name == "ashare-dashboard.html"
    assert target.stat().st_size > 5000
