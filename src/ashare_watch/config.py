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
#   国内贵金属 → 上海金交所/上期所的国内金价，比伦敦金更贴近 A 股黄金股
#   能源     → 石油石化、航空、化工成本
#   基本金属 → 有色板块、制造业成本
#   黑色系   → 地产、基建、钢铁与煤炭股的景气度
#   化工     → 化纤、煤化工、纯碱玻璃这条链
#   农产品   → 食品饲料、纺织服装的成本端
#   海外股指 → 隔夜外盘情绪，开盘前的风向标
#   外汇     → 外资流向、出口链、美元流动性
#   数字货币 → 全球风险偏好的温度计
MACRO_GROUPS: dict[str, tuple[tuple[str, str], ...]] = {
    "贵金属": (
        ("hf_XAU", "伦敦金"),
        ("hf_GC", "纽约黄金"),
        ("hf_XAG", "伦敦银"),
        ("hf_SI", "纽约白银"),
        ("hf_XPT", "伦敦铂金"),
        ("hf_XPD", "伦敦钯金"),
    ),
    "国内贵金属": (
        ("nf_AU0", "沪金主力"),
        ("nf_AG0", "沪银主力"),
    ),
    "能源": (
        ("hf_CL", "WTI 原油"),
        ("hf_OIL", "布伦特原油"),
        ("hf_NG", "天然气"),
        ("nf_SC0", "原油 SC"),
    ),
    "基本金属": (
        ("hf_CAD", "伦铜"),
        ("hf_AHD", "伦铝"),
        ("hf_ZSD", "伦锌"),
        ("hf_NID", "伦镍"),
        ("nf_CU0", "沪铜主力"),
        ("nf_AL0", "沪铝主力"),
    ),
    "黑色系": (
        ("nf_RB0", "螺纹钢"),
        ("nf_I0", "铁矿石"),
        ("nf_JM0", "焦煤"),
        ("nf_J0", "焦炭"),
    ),
    "化工": (
        ("nf_TA0", "PTA"),
        ("nf_MA0", "甲醇"),
        ("nf_SA0", "纯碱"),
    ),
    "农产品": (
        ("nf_M0", "豆粕"),
        ("nf_CF0", "郑棉"),
        ("nf_SR0", "白糖"),
    ),
    "海外股指": (
        ("hf_ES", "标普500期货"),
        ("hf_NQ", "纳指100期货"),
        ("hf_YM", "道指期货"),
        ("hf_HSI", "恒指期货"),
        ("hf_CHA50CFD", "富时A50期货"),
    ),
    "外汇": (
        ("DINIW", "美元指数"),
        ("fx_susdcny", "美元人民币"),
        ("fx_susdcnh", "离岸人民币"),
        ("fx_seurusd", "欧元美元"),
        ("fx_susdjpy", "美元日元"),
        ("fx_sgbpusd", "英镑美元"),
        ("fx_saudusd", "澳元美元"),
        ("fx_snzdusd", "纽元美元"),
        ("fx_seurgbp", "欧元英镑"),
        ("fx_seurjpy", "欧元日元"),
        ("fx_sgbpjpy", "英镑日元"),
        ("fx_susdhkd", "美元港元"),
        ("fx_susdcad", "美元加元"),
        ("fx_susdchf", "美元瑞郎"),
        ("fx_susdsgd", "美元新加坡元"),
        ("fx_susdkrw", "美元韩元"),
        ("fx_susdthb", "美元泰铢"),
        ("fx_susdzar", "美元南非兰特"),
        ("fx_susdbrl", "美元巴西雷亚尔"),
        ("fx_susdinr", "美元印度卢比"),
        ("fx_scnyjpy", "人民币日元"),
        ("fx_seurcny", "人民币欧元"),
    ),
    "数字货币": (
        ("fx_sbtcusd", "比特币"),
    ),
}


def default_macro_symbols() -> list[str]:
    """把分组拍平成一个代码列表。实际请求会按 MACRO_CHUNK_SIZE 分批取。"""
    return [symbol for group in MACRO_GROUPS.values() for symbol, _ in group]


# 计价单位。黄金看的是美元/盎司，原油看美元/桶，伦铜看美元/吨——
# 不写清楚单位，光一个数字看不出量级是否正常。
MACRO_UNITS: dict[str, str] = {
    "hf_XAU": "美元/盎司",
    "hf_GC": "美元/盎司",
    "hf_XAG": "美元/盎司",
    "hf_SI": "美元/盎司",
    "hf_XPT": "美元/盎司",
    "hf_XPD": "美元/盎司",
    "nf_AU0": "元/克",
    "nf_AG0": "元/千克",
    "hf_CL": "美元/桶",
    "hf_OIL": "美元/桶",
    "hf_NG": "美元/百万英热",
    "nf_SC0": "元/桶",
    "hf_CAD": "美元/吨",
    "hf_AHD": "美元/吨",
    "hf_ZSD": "美元/吨",
    "hf_NID": "美元/吨",
    "nf_CU0": "元/吨",
    "nf_AL0": "元/吨",
    "nf_RB0": "元/吨",
    "nf_I0": "元/吨",
    "nf_JM0": "元/吨",
    "nf_J0": "元/吨",
    "nf_TA0": "元/吨",
    "nf_MA0": "元/吨",
    "nf_SA0": "元/吨",
    "nf_M0": "元/吨",
    "nf_CF0": "元/吨",
    "nf_SR0": "元/吨",
    "hf_ES": "点",
    "hf_NQ": "点",
    "hf_YM": "点",
    "hf_HSI": "点",
    "hf_CHA50CFD": "点",
    "fx_sbtcusd": "美元/枚",
    "DINIW": "点",
}

# 一批最多带多少个品种。
# 新浪的 list= 拼在 URL 里，品种涨到 50 多个以后 URL 会偏长；
# 拆成两批并发取比压着一个超长 URL 更稳，成本也只是多一个请求。
MACRO_CHUNK_SIZE = 40


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
    # 盘中刷新间隔。15 秒是实测出来的甜点：
    #   * 一次「快速轮次」只发 2 个请求（指数+自选股批量、环球市场），
    #     全市场那 56 页是按 TTL 缓存的，跟这个间隔无关；
    #   * 所以从 60 秒提到 15 秒，请求量只从 20.7 涨到 22.0 请求/分钟；
    #   * 下限是 2 秒——完整采集要 6.4 秒，间隔比它小会请求重叠堆积。
    refresh_seconds: int = field(
        default_factory=lambda: _env_int("ASHARE_WATCH_REFRESH_SECONDS", 15)
    )
    idle_seconds: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_IDLE_SECONDS", 900))
    # 全市场快照缓存。它占了 97% 的请求量（一次要翻 56 页），
    # 所以这里松一点，把省下来的额度让给指数和自选股的快速刷新。
    # 影响的是榜单/宽度/涨跌停统计的滞后时间，最多 4 分钟。
    universe_ttl: int = field(default_factory=lambda: _env_int("ASHARE_WATCH_UNIVERSE_TTL", 240))
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

    # 刷新间隔的硬下限。完整采集（含全市场 56 页）实测 6.4 秒，
    # 间隔比它小只会让请求重叠堆积，所以这里设一个地板拦住自己。
    min_refresh_seconds: int = 2

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
    macro_chunk_size: int = field(
        default_factory=lambda: _env_int("ASHARE_WATCH_MACRO_CHUNK_SIZE", MACRO_CHUNK_SIZE)
    )

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

    @property
    def search_index_path(self) -> Path:
        """搜索索引的本地缓存，用于断网时兜底。"""
        return self.data_dir / "search-index.json"


_SETTINGS: Settings | None = None


def get_settings(refresh: bool = False) -> Settings:
    global _SETTINGS
    if _SETTINGS is None or refresh:
        _SETTINGS = Settings()
    return _SETTINGS
