"""启动仪表盘：`python scripts/serve.py`"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ashare_watch.config import get_settings  # noqa: E402
from ashare_watch.server import serve  # noqa: E402


def main() -> int:
    settings = get_settings()
    # Windows 上中文输出有个坑：stdout 被重定向到文件时 Python 会用系统编码
    # （简体中文是 GBK），遇到表示不了的字符会直接抛 UnicodeEncodeError
    # 把服务打挂。errors="replace" 让它退化成问号，服务继续跑。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(settings.log_path, encoding="utf-8"),
        ],
    )
    serve(settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

