"""前端静态检查。

这一层不做浏览器测试（CI 里没有浏览器，也不该为了一个个人看板引入
Playwright），只钉住几条「踩过一次就再也不想踩」的不变量。
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "ashare_watch" / "static"
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")


def test_follow_state_is_initialised_after_its_helpers():
    """关注列表的初始化顺序。

    真实踩过的坑：``const FOLLOW_STATE = loadFollowState();`` 一度排在
    ``isStockCode`` 前面，撞上 JS 的暂时性死区直接抛异常；而那个函数内部
    套着 try/catch，异常被吞掉之后的表现是「刷新一下关注列表就全没了」，
    查起来非常费劲。这里只锁一个顺序约束，成本很低。
    """
    call_at = APP_JS.index("const FOLLOW_STATE = loadFollowState();")
    assert APP_JS.index("function loadFollowState()") < call_at
    assert APP_JS.index("function isStockCode(") < call_at


def test_every_element_id_looked_up_exists_in_the_markup():
    """``$("xxx")`` 里的每个 id，index.html 里都必须真的有。

    写错一个字母页面不会报错，只会在运行时静默少一块内容。
    """
    looked_up = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', APP_JS))
    declared = set(re.findall(r'id="([A-Za-z0-9_-]+)"', INDEX_HTML))
    # 有些 id 是运行时才生成的，不要求出现在静态 HTML 里
    runtime_only = {
        "detail-daily", "detail-flow", "detail-intraday", "detail-orderbook",
    }
    missing = sorted(looked_up - declared - runtime_only)
    assert not missing, f"app.js 里查找了不存在的元素：{missing}"


def test_follow_panel_is_present_in_the_markup():
    for element_id in ("follow-panel", "follow-list", "follow-count", "follow-clear"):
        assert f'id="{element_id}"' in INDEX_HTML


def test_html_comments_are_closed():
    """注释必须闭合。

    真实踩过的坑：把结尾写成了 ``*/`` 而不是 ``-->``，于是整段标记被当成注释
    吞掉——元素在文件里明明"存在"，浏览器里却是 null，报错还指向 JS，
    查起来要绕一大圈。
    """
    assert INDEX_HTML.count("<!--") == INDEX_HTML.count("-->")
    assert "*/" not in INDEX_HTML.split("<script")[0], "HTML 注释应该用 --> 收尾"
