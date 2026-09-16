"""命令行入口：``ashare-watch serve`` / ``fetch`` / ``export`` / ``status``。"""

from __future__ import annotations

import argparse
import logging
import sys

from ashare_watch.collector import Collector
from ashare_watch.config import get_settings
from ashare_watch.render import export_snapshot
from ashare_watch.server import serve
from ashare_watch.store import SnapshotStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ashare-watch", description="A 股实时行情")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="启动本地仪表盘（默认）")
    sub.add_parser("fetch", help="抓取一次数据")
    sub.add_parser("export", help="导出单文件 HTML 快照")
    sub.add_parser("status", help="查看本地数据与采集日志")

    args = parser.parse_args(argv)
    settings = get_settings()
    settings.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s  %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )

    if args.command in (None, "serve"):
        serve(settings)
        return 0
    if args.command == "fetch":
        snapshot = Collector(settings=settings).refresh()
        print(
            f"已抓取：{snapshot.fetched_at}  {snapshot.market.status}  "
            f"{len(snapshot.indexes)} 指数 / {len(snapshot.watchlist)} 自选股 / "
            f"{snapshot.coverage.get('universe', 0)} 只全市场"
        )
        return 0
    if args.command == "export":
        data = SnapshotStore(settings.db_path).latest_snapshot()
        if data is None:
            data = Collector(settings=settings).refresh().to_dict()
        print(f"已导出：{export_snapshot(data, settings)}")
        return 0
    if args.command == "status":
        store = SnapshotStore(settings.db_path)
        counts = store.count()
        print(f"快照数：{counts['snapshots']}    采集次数：{counts['runs']}")
        latest = store.latest_snapshot()
        if latest:
            print(f"最新数据时间：{latest.get('fetched_at')}")
            print(f"市场状态：{(latest.get('market') or {}).get('status')}")
        for run in store.recent_runs(8):
            print(
                f"  {run['finished_at'][:19]}  {run['status']:<8} "
                f"{run['duration_ms']:>7.0f}ms  请求 {run['requests']}  失败 {run['failures']}"
            )
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

