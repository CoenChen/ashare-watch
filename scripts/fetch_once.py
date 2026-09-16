"""抓一次数据并打印结果：`python scripts/fetch_once.py [--export]`

用于验证接口是否正常、配合 Windows 计划任务定时抓取、以及在 CI 里做冒烟测试。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_watch.collector import Collector  # noqa: E402
from ashare_watch.config import get_settings  # noqa: E402
from ashare_watch.render import export_snapshot  # noqa: E402
from ashare_watch.structure import format_money, format_shares  # noqa: E402


def main(argv: list[str]) -> int:
    settings = get_settings()
    snapshot = Collector(settings=settings).refresh()

    print("=" * 76)
    print(f"采集完成  {snapshot.fetched_at}  耗时 {snapshot.generated_ms / 1000:.1f}s")
    print(f"市场状态：{snapshot.market.status}"
          + (f"（{snapshot.market.session}）" if snapshot.market.session else ""))
    print("=" * 76)

    for quote in snapshot.indexes:
        sign = "+" if (quote.change_pct or 0) >= 0 else ""
        print(f"  {quote.name:<10} {quote.sina:<9} "
              f"{quote.price:>12,.2f}  {sign}{quote.change_pct:.2f}%")

    print(f"\n  自选股 {len(snapshot.watchlist)} 只：")
    for quote in snapshot.watchlist[:8]:
        sign = "+" if (quote.change_pct or 0) >= 0 else ""
        tag = f"  [{quote.limit_status}]" if quote.limit_status else ""
        print(f"    {quote.code} {quote.name:<8} {quote.price:>10,.2f}  "
              f"{sign}{quote.change_pct:.2f}%{tag}")
    if len(snapshot.watchlist) > 8:
        print(f"    … 其余 {len(snapshot.watchlist) - 8} 只")

    b = snapshot.breadth
    print(f"\n  市场宽度：上涨 {b.get('advancers', 0)} / 下跌 {b.get('decliners', 0)} "
          f"/ 平盘 {b.get('unchanged', 0)}")
    lim = snapshot.limits
    print(f"  涨跌停：涨停 {lim.get('涨停家数', 0)} 家（一字 {lim.get('一字涨停', 0)}）"
          f" / 跌停 {lim.get('跌停家数', 0)} 家 / 炸板 {lim.get('炸板家数', 0)} 家")
    print(f"  全市场样本：{snapshot.coverage.get('universe', 0)} 只")

    if snapshot.gainers:
        top = snapshot.gainers[0]
        print(f"  涨幅第一：{top.code} {top.name} {top.change_pct:+.2f}%")
    if snapshot.sectors:
        print(f"  最强板块：{snapshot.sectors[0].name} {snapshot.sectors[0].change_pct:+.2f}%")
        print(f"  最弱板块：{snapshot.sectors[-1].name} {snapshot.sectors[-1].change_pct:+.2f}%")
    if snapshot.most_active:
        top = snapshot.most_active[0]
        print(f"  成交额第一：{top.code} {top.name} {format_money(top.amount)}")

    for warning in snapshot.warnings:
        print(f"  ⚠ {warning}")

    if "--export" in argv:
        target = export_snapshot(snapshot.to_dict(), settings)
        print(f"\n已导出单文件快照：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

