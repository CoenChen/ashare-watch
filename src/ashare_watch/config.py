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

# 环球市场：影响 A 股的外部变量。
# 分组展示，因为这几类对 A 股的传导路径完全不同：
#   贵金属   → 避险情绪、黄金股
#   能源     → 石油石化、航空、化工成本
#   基本金属 → 有色板块、制造业成本
#   外汇     → 外资流向、出口链、美元流动性
MACRO_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "贵金属": (
        ("hf_XAU", "伦敦金"),
        ("hf_GC", "纽约黄金"),
        ("hf_SI", "纽约白银"),
    ),
    "能源": (
        ("hf_CL", "WTI 原油"),
        ("hf_OIL", "布伦特原油"),
    ),
    "基本金属": (
        ("hf_CAD", "伦铜"),
    ),
    "外汇": (
        ("DINIW", "美元指数"),
        ("fx_susdcny", "美元人民币"),
        ("fx_seurusd", "欧元美元"),
        ("fx_susdjpy", "美元日元"),
    ),
}


def default_macro_symbols() -> list[str]:
    """把分组拍平成一个代码列表，用于一次批量请求。"""
    return [symbol for group in MACRO_GROUPS.values() for symbol, _ in group]


# 计价单位。黄金看的是美元/盎司，原油看美元/桶，伦铜看美元/吨——
# 不写清楚单位，光一个数字看不出量级是否正常。
MACRO_UNITS: dict[str, str] = {
    "hf_XAU": "美元/盎司",
    "hf_GC": "美元/盎司",
    "hf_SI": "美元/盎司",
    "hf_CL": "美元/桶",
    "hf_OIL": "美元/桶",
    "hf_CAD": "美元/吨",
    "DINIW": "点",
}


def macro_group_of(symbol: str) -> str:
    for group, items in MACRO_GROUPS.items():
        if any(item[0] == symbol for item in items):
            return group
    return "其他"


def macro_name_of(symbol: str) -> str:
    for items in MACRO_GROUPS.values():
        for code, name in items:
            if code == symbol:
                return name
    return symbol


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
    macro_symbols: list[str] = field(default_factory=lambda: default_macro_symbols())

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
