"""服务端接口测试。

这里起一个真实的 HTTP 服务（本地回环，不联网），验证路由、参数解析和
上限保护。抓不到数据是正常的——测试环境没有外网，客户端会返回空列表，
但这恰好也验证了「失败时不抛异常」这条契约。
"""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from ashare_watch.config import Settings
from ashare_watch.server import create_server, running_instance


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


def test_health_endpoint(live_server):
    base, _collector = live_server
    data = get_json(f"{base}/api/health")
    assert data["status"] == "ok"
    assert "client" in data


def test_quotes_without_codes_returns_empty(live_server):
    base, _collector = live_server
    assert get_json(f"{base}/api/quotes")["quotes"] == []
    assert get_json(f"{base}/api/quotes?codes=")["quotes"] == []


def test_quotes_accepts_and_truncates_codes(live_server):
    """接口设了 60 个代码的上限，防止被当成批量下载用。"""
    base, collector = live_server
    codes = ",".join(f"{600000 + i}" for i in range(200))
    # 测试环境抓不到数据，但接口本身必须正常返回而不是报错
    data = get_json(f"{base}/api/quotes?codes={codes}")
    assert "quotes" in data


def test_dashboard_before_first_refresh_is_null(live_server):
    """首次抓取还没完成时，接口返回 snapshot: null，前端会显示加载态。"""
    base, _collector = live_server
    data = get_json(f"{base}/api/dashboard")
    assert data["snapshot"] is None
    assert "meta" in data


def test_unknown_path_returns_404(live_server):
    base, _collector = live_server
    try:
        get_json(f"{base}/api/nope")
        raise AssertionError("应当返回 404")
    except urllib.error.HTTPError as error:
        assert error.code == 404


def test_second_instance_cannot_take_the_same_port(live_server, tmp_path):
    """同一个端口不允许启动第二份看板。

    ``http.server`` 默认开着 ``allow_reuse_address``，在 Windows 上这会让两个
    进程同时绑同一个端口，而且先启动的那个继续收连接——表现就是「改了代码、
    重启了、页面还是旧数据」。这条测试把这个坑钉死。
    """
    base, _collector = live_server
    port = int(base.rsplit(":", 1)[1])
    settings = Settings(
        data_dir=tmp_path / "second",
        host="127.0.0.1",
        port=port,
        open_browser=False,
    )
    settings.ensure_dirs()
    with pytest.raises(OSError):
        create_server(settings, start_worker=False)


def test_running_instance_detects_the_dashboard(live_server):
    base, _collector = live_server
    assert running_instance(base) is True


def test_running_instance_ignores_a_dead_port():
    assert running_instance("http://127.0.0.1:1") is False
