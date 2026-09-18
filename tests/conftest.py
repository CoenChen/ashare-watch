"""共用的测试夹具。

`live_server` 在一个随机端口上起一个真实的 HTTP 服务（不联网），
接口测试都用它——既验证了路由，也顺带验证了「抓不到数据时不抛异常」。
"""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from ashare_watch.config import Settings
from ashare_watch.server import create_server


@pytest.fixture
def live_server(tmp_path):
    """在随机端口上起一个真实服务。"""
    settings = Settings(
        data_dir=tmp_path / "data",
        host="127.0.0.1",
        port=0,          # 让系统分配空闲端口，避免和正在运行的看板撞号
        open_browser=False,
    )
    settings.ensure_dirs()
    # start_worker=False：测试只验接口，不需要后台抓取线程
    httpd, state, worker, collector = create_server(settings, start_worker=False)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", collector
    finally:
        httpd.shutdown()
        httpd.server_close()
        collector.store.close()


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))
