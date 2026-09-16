"""限流处理测试。

新浪在请求过密时会返回 **HTTP 456**。第一版代码把它当成普通失败重试，
结果越试越糟——重试本身就在加重限流。正确做法是：识别出来、退避、
少试一次，并且把"被限流"这个事实报给上层。

这个测试用假的 HTTP 连接模拟限流，不联网。
"""

from __future__ import annotations

import pytest

from ashare_watch.client import RATE_LIMIT_STATUS, SinaClient
from ashare_watch.config import Settings


class FakeResponse:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self.reason = "test"
        self.headers: dict = {}
        self._body = body

    def read(self) -> bytes:
        return self._body


class FakeConnection:
    """按顺序返回预设的响应，并记录被调用了几次。"""

    def __init__(self, statuses: list[int], body: bytes = b'{"ok":1}') -> None:
        self._statuses = list(statuses)
        self._body = body
        self.calls = 0

    def request(self, *_args, **_kwargs) -> None:
        self.calls += 1

    def getresponse(self) -> FakeResponse:
        status = self._statuses.pop(0) if self._statuses else 200
        if status == 200:
            return FakeResponse(200, self._body)
        return FakeResponse(status, b"")

    def close(self) -> None:
        pass


@pytest.fixture
def no_sleep(monkeypatch):
    """把退避的 sleep 换掉，避免测试真的等几秒。"""
    slept: list[float] = []
    monkeypatch.setattr("ashare_watch.client.time.sleep", lambda s: slept.append(s))
    return slept


def build_client(statuses: list[int], **overrides) -> tuple[SinaClient, FakeConnection]:
    settings = Settings(data_dir="/tmp/ashare-watch-test", **overrides)
    client = SinaClient(settings)
    connection = FakeConnection(statuses)
    client._connection = lambda host: connection  # type: ignore[assignment]
    return client, connection


def test_rate_limit_is_recognised():
    assert 456 in RATE_LIMIT_STATUS
    assert 429 in RATE_LIMIT_STATUS


def test_rate_limit_backs_off_and_gives_up_quickly(no_sleep):
    """被限流时应退避一次、再试一次就放弃，而不是连试三次。"""
    client, connection = build_client([456, 456, 456])
    result = client._request("hq.sinajs.cn", "/list=sh000001")
    assert result is None
    assert connection.calls == 2, f"被限流时不应连续重试，实际请求了 {connection.calls} 次"
    assert client.stats["rate_limited"] == 2
    # 退避时间应该等于配置值
    assert no_sleep and no_sleep[0] == client.settings.rate_limit_backoff


def test_rate_limit_recovers_when_server_lets_up(no_sleep):
    client, connection = build_client([456, 200])
    result = client._request("hq.sinajs.cn", "/list=sh000001")
    assert result == b'{"ok":1}'
    assert connection.calls == 2
    assert client.stats["rate_limited"] == 1
    assert client.stats["failures"] == 0


def test_client_error_is_not_retried(no_sleep):
    """400/403/404 是客户端错误，重试没有意义，应该立刻放弃。"""
    client, connection = build_client([404, 200])
    result = client._request("hq.sinajs.cn", "/nope")
    assert result is None
    assert connection.calls == 1


def test_universe_reports_completeness(no_sleep, monkeypatch):
    """全市场抓取必须给出完整性指标，供上层提示用户。"""
    client, _connection = build_client([200])
    monkeypatch.setattr(client, "universe_count", lambda: 5000)

    def fake_pages(pages, merged, *, delay=0.0):
        page_list = list(pages)
        # 每页返回 page_size 条，模拟真实分页
        def fill(page: int) -> None:
            for offset in range(client.settings.page_size):
                merged[f"{page:04d}{offset:04d}"] = None  # type: ignore[assignment]

        # 第一轮故意漏掉最后一页，第二轮补上
        if not delay:
            missing = [page_list[-1]]
            for page in page_list[:-1]:
                fill(page)
            return missing
        for page in page_list:
            fill(page)
        return []

    monkeypatch.setattr(client, "_fetch_pages", fake_pages)
    client.universe()
    assert client.last_universe_expected == 5000
    assert client.last_completeness > 0.9
