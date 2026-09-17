"""把当前数据导出成**单文件 HTML**。

这是最省事的形态：双击就能在浏览器打开，不需要装 Python、不需要开服务、
不需要联网。样式、脚本、数据全部内联在一个文件里，可以直接发给别人。

实现上复用同一套前端模板（``static/``），把外链的 CSS 与 JS 替换成内联内容。
这样线上服务和离线快照永远是同一份界面代码，不会出现"改了网页忘了改导出"。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ashare_watch.config import Settings, get_settings

STATIC_DIR = Path(__file__).parent / "static"


def _read_static(name: str) -> str:
    path = STATIC_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"缺少前端资源：{path}")
    return path.read_text(encoding="utf-8")


def _inline(payload: object) -> str:
    """序列化并转义，避免数据里的 </script> 提前闭合脚本标签。"""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/")


def build_standalone_html(
    snapshot: dict,
    *,
    title: str = "A 股实时行情",
    search_index: list[list] | None = None,
) -> str:
    """把快照（和可选的搜索索引）内联进单个 HTML 文件。

    搜索索引单独一个参数而不是塞进 snapshot：它是两百多 KB 的数组，
    混进快照会让快照本身难以阅读，也会撑大存进 SQLite 的历史记录。
    """
    html = _read_static("index.html")
    css = _read_static("styles.css")
    js = _read_static("app.js")

    html = re.sub(
        r'<link[^>]*href="/static/styles\.css"[^>]*/?>',
        f"<style>\n{css}\n</style>",
        html,
    )
    html = re.sub(
        r'<script[^>]*src="/static/app\.js"[^>]*></script>',
        f"<script>\n{js}\n</script>",
        html,
    )

    injected = f"<script>window.__SNAPSHOT__ = {_inline(snapshot)};"
    if search_index:
        injected += f"window.__SEARCH_INDEX__ = {_inline(search_index)};"
    injected += "</script>\n<script>"
    html = html.replace("<script>", injected, 1)
    html = html.replace(
        "<title>A 股实时行情</title>",
        f"<title>{title} · {snapshot.get('fetched_at', '')}</title>",
    )
    html = html.replace(
        "</body>",
        # 只写数据时间，不写「导出于当前时刻」：同一份快照应该产出**完全相同**的
        # 文件，否则每次构建都会产生一行无意义的 diff（实测就是这样）。
        f"<!-- 数据时间 {snapshot.get('fetched_at', '')} -->\n</body>",
        1,
    )
    return html


def export_snapshot(
    snapshot: dict,
    settings: Settings | None = None,
    *,
    search_index: list[list] | None = None,
) -> Path:
    settings = settings or get_settings()
    settings.ensure_dirs()
    target = settings.export_path
    target.write_text(
        build_standalone_html(snapshot, search_index=search_index),
        encoding="utf-8",
        # 显式写 LF：.gitattributes 要求 eol=lf，如果这里跟着 Windows 写成 CRLF，
        # 每次构建后 git 都会把文件标成「已修改」，产生无意义的 diff。
        newline="\n",
    )
    return target
