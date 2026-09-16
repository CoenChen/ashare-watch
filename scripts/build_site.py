"""构建可部署的静态站点：`python scripts/build_site.py --out docs`

产出的是一个**单文件** `index.html`（样式、脚本、数据全部内联），可以直接
放到任何静态托管上：GitHub Pages、Cloudflare Pages、Vercel、对象存储……

为什么坚持单文件而不是拆成 index.html + css + js 三个文件？
因为分享场景下最怕的是"少传一个文件，页面打开是白板"。单文件不存在这个问题，
也方便直接当附件发。

默认会用本地最近一次快照；加 ``--refresh`` 会先抓一次最新数据。
如果抓取失败但有本地快照，会自动退回用快照，**不会因为一次网络抖动
就把线上页面弄成空白**。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_watch.collector import Collector  # noqa: E402
from ashare_watch.config import get_settings  # noqa: E402
from ashare_watch.render import build_standalone_html  # noqa: E402
from ashare_watch.store import SnapshotStore  # noqa: E402

# 交给 Pages 的静态文件里不要有 Jekyll 处理步骤：
# 一是没必要，二是它会忽略下划线开头的文件，容易踩坑。
NOJEKYLL = ""


def get_snapshot(*, refresh: bool) -> tuple[dict, str]:
    """返回 ``(快照数据, 来源说明)``。"""
    settings = get_settings()
    settings.ensure_dirs()
    store = SnapshotStore(settings.db_path)

    if refresh:
        try:
            snapshot = Collector(settings=settings, store=store).refresh()
            return snapshot.to_dict(), "刚刚抓取"
        except Exception as error:  # noqa: BLE001
            print(f"[警告] 抓取失败（{type(error).__name__}: {error}），尝试使用本地快照")

    cached = store.latest_snapshot()
    if cached:
        return cached, "本地快照"
    raise SystemExit(
        "没有可用数据：既没能抓取成功，本地也没有快照。"
        "请检查网络后重新运行，或先执行 python scripts/fetch_once.py"
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="构建可部署的静态站点")
    parser.add_argument("--out", default="docs", help="输出目录（默认 docs）")
    parser.add_argument("--refresh", action="store_true", help="先抓取一次最新数据")
    args = parser.parse_args(argv)

    data, origin = get_snapshot(refresh=args.refresh)
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    html = build_standalone_html(data, title="A 股行情快照")
    target = out_dir / "index.html"
    target.write_text(html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text(NOJEKYLL, encoding="utf-8")

    size_kb = target.stat().st_size / 1024
    coverage = data.get("coverage", {})
    print(f"站点已构建：{target}")
    print(f"  数据来源：{origin}")
    print(f"  数据时间：{data.get('fetched_at', '')}")
    print(f"  市场状态：{(data.get('market') or {}).get('status', '')}")
    print(f"  文件大小：{size_kb:.0f} KB")
    print(f"  覆盖范围：{coverage.get('universe', 0)} 只个股 / "
          f"{coverage.get('sectors', 0)} 个板块 / {coverage.get('indexes', 0)} 个指数")
    print()
    print("把这个目录部署到任意静态托管即可获得一个可以发微信的链接：")
    print("  GitHub Pages：仓库 Settings → Pages → Source 选 Deploy from a branch，")
    print("                分支选 main，目录选 /docs，保存后等 1 分钟。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

