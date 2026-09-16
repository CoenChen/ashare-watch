from __future__ import annotations

from ashare_watch.config import Settings
from ashare_watch.render import build_standalone_html, export_snapshot
from ashare_watch.store import SnapshotStore


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

