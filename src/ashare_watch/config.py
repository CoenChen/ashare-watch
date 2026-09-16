"""配置集中管理，全部可用环境变量覆盖。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 默认自选股：各行业龙头，都是沪深两市流动性最好的品种之一。
DEFAULT_SYMBOLS: tuple[str, ...] = (
    "600519",  # 贵州茅台
    "300750",  # 宁德时代
    "601318",  # 中国平安
    "000858",  # 五粮液
    "600036",  # 招商银行
    "002594",  # 比亚迪
    "688981",  # 中芯国际
    "601012",  # 隆基绿能
    "300059",  # 东方财富
    "000725",  # 京东方A
    "000333",  # 美的集团
    "600900",  # 长江电力
    "600276",  # 恒瑞医药
    "601899",  # 紫金矿业
    "601888",  # 中国中免
    "002475",  # 立讯精密
    "603501",  # 韦尔股份
    "603259",  # 药明康德
    "600309",  # 万华化学
    "600030",  # 中信证券
)

# 顶部大卡展示的指数（新浪代码）
DEFAULT_INDEXES: tuple[str, ...] = (
    "sh000001",  # 上证指数
    "sz399001",  # 深证成指
    "sz399006",  # 创业板指
    "sh000688",  # 科创50
    "sh000300",  # 沪深300
)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_symbols(name: str) -> list[str]:
    """解析自选股。支持 ``600519`` 与 ``sh600519`` 两种写法，统一成 6 位代码。"""
    raw = os.getenv(name, "")
    if not raw.strip():
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw.replace("，", ",").split(","):
        text = item.strip().lower()
        if not text:
            continue
        for prefix in ("sh", "sz", "bj"):
            if text.startswith(prefix):
                text = text[len(prefix) :]
                break
        if text.isdigit() and len(text) == 6 and text not in seen:
            seen.add(text)
            out.append(text)
    return out


@dataclass(slots=True)
class Settings:
    refresh_seconds: int = field(
        default_factory=lambda: _env_int("ASHARE_WATCH_REFRESH_SECONDS", 60)
    )
    idle_seconds: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_IDLE_SECONDS", 900))
    universe_ttl: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_UNIVERSE_TTL", 180))
    sector_ttl: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_SECTOR_TTL", 300))
    history_ttl: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_HISTORY_TTL", 21600))

    # 并发数。全市场要翻 56 页，并发太低会很慢，太高会被限流（实测新浪会返回
    # HTTP 456）。8 并发配合连接复用是实测下来又稳又快的平衡点。
    workers: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_WORKERS", 8))
    timeout: float = field(default_factory=lambda: float(_env_int("ASHARE_WATCH_TIMEOUT", 20)))
    retries: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_RETRIES", 3))
    # 同一进程内两次请求的最小间隔。这个值太小同样会触发限流。
    min_request_interval: float = 0.08
    # 被限流之后的退避时间（秒）。限流窗口通常持续几秒，退避太短没意义。
    rate_limit_backoff: float = 2.5
    page_size: int = 100

    host: str = field(default_factory=lambda: os.getenv("ASHARE_WATCH_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_PORT", 8771))
    open_browser: bool = field(
        default_factory=lambda: not _env_bool("ASHARE_WATCH_NO_BROWSER", False)
    )

    symbols: list[str] = field(
        default_factory=lambda: _env_symbols("ASHARE_WATCH_SYMBOLS") or list(DEFAULT_SYMBOLS)
    )
    indexes: list[str] = field(default_factory=lambda: list(DEFAULT_INDEXES))

    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ASHARE_WATCH_DATA_DIR", PROJECT_ROOT / "data"))
    )

    def __post_init__(self) -> None:
        # dataclass 不做类型转换，直接传字符串进来会在 mkdir 时炸掉
        self.data_dir = Path(self.data_dir)
        self.symbols = [s for s in self.symbols if s]
        self.indexes = [s for s in self.indexes if s]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "exports").mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "market.sqlite3"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "watch.log"

    @property
    def export_path(self) -> Path:
        return self.data_dir / "exports" / "ashare-dashboard.html"


_SETTINGS: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _SETTINGS
    if _SETTINGS is None or refresh:
        _SETTINGS = Settings()
    return _SETTINGS
