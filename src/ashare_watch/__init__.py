"""A 股实时行情仪表盘 · 本地抓取，零第三方依赖。

模块地图::

    config.py     配置（全部可用环境变量覆盖）
    models.py     数据结构：行情、市场状态、快照
    structure.py  解析工具（新浪的 GBK 文本 / JS 变量 / 分页 JSON）
    market.py     A 股交易规则：交易时段、板块判定、涨跌停识别
    client.py     数据源客户端（连接复用 / 重试 / 缓存 / 并发）
    derive.py     派生指标：榜单、市场宽度、涨跌停统计
    collector.py  采集编排
    store.py      SQLite：快照历史 + 采集日志
    render.py     导出单文件 HTML
    server.py     零依赖 HTTP 服务 + 后台定时刷新
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["__version__"]

