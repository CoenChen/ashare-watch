"""把最近一次快照导出成单文件 HTML：`python scripts/export_html.py [--refresh]`"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_watch.collector import Collector  # noqa: E402
from ashare_watch.config import get_settings  # noqa: E402
from ashare_watch.render import export_snapshot  # noqa: E402
from ashare_watch.store import SnapshotStore  # noqa: E402


def main(argv: list[str]) -> int:
    settings = get_settings()
    settings.ensure_dirs()
    if "--refresh" in argv:
        data = Collector(settings=settings).refresh().to_dict()
    else:
        data = SnapshotStore(settings.db_path).latest_snapshot()
        if data is None:
            print("本地还没有数据，正在抓取一次…")
            data = Collector(settings=settings).refresh().to_dict()

    index: list[list] = []
    try:
        index = Collector(settings=settings).search_index()
    except Exception:  # noqa: BLE001
        pass

    target = export_snapshot(data, settings, search_index=index)
    print(f"已导出：{target}")
    print(f"  大小：{target.stat().st_size / 1024:.0f} KB")
    print(f"  数据时间：{data.get('fetched_at', '')}")
    print(f"  搜索索引：{len(index)} 只")
    print("  双击文件即可在浏览器打开，不需要联网。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
