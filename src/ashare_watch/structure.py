"""解析工具：把三个数据源各自的格式转成干净的数据。

三个源、三种格式，各有各的坑：

* ``hq.sinajs.cn`` —— GBK 编码的 JS 变量，字段按位置排列（没有字段名）
* ``Market_Center.getHQNodeData`` —— 标准 JSON，但中文可能用 ``\\uXXXX`` 转义
* ``newSinaHy.php`` —— GBK 编码的 JS **对象**，值是一长串逗号分隔的字段

所有解析都集中在这个文件里，任何格式变化只需要改这里。
"""

from __future__ import annotations

import json
import re

NULL_TOKENS = {"", "--", "-", "null", "None", "N/A"}

# 代码格式不止一种：A 股是 sh600519，外盘期货是 hf_XAU，外汇是 fx_susdcny，
# 美元指数干脆就是 DINIW。所以这里放宽成「字母数字下划线」，
# 不能再用 [a-z]{2}\d{6} 这种只管 A 股的写法。
_SINA_LINE = re.compile(r'var\s+hq_str_([A-Za-z0-9_]+)="([^"]*)"')
_JS_OBJECT = re.compile(r"=\s*(\{.*\})\s*;?\s*$", re.S)


def decode_gbk(raw: bytes) -> str:
    """新浪多数接口用 GBK 返回中文，解码失败时降级而不是抛异常。"""
    for encoding in ("gbk", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("gbk", "replace")


def clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text in NULL_TOKENS:
        return ""
    return text.replace(",", "")


def parse_number(value: object) -> float | None:
    """解析数字，失败返回 ``None``。缺字段不应该让整份数据作废。"""
    text = clean(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_percent(value: object) -> float | None:
    text = clean(value).replace("%", "").replace("+", "")
    return parse_number(text)


def parse_compact(value: object, unit: str = "万") -> float | None:
    """新浪市值字段的单位是**万元**，这里换算成元，避免前端再猜单位。"""
    number = parse_number(value)
    if number is None:
        return None
    return number * 10_000 if unit == "万" else number


# --------------------------------------------------------------------------- #
# 代码与数据源代码互转
# --------------------------------------------------------------------------- #
def to_sina_symbol(code: str) -> str:
    """``600519`` → ``sh600519``；已经是 ``sh600519`` 就原样返回。

    规则：6/9 开头是沪市（含科创板 688、北交所 920 需单独判断），
    0/2/3 开头是深市，4/8 开头是北交所。
    """
    text = code.strip().lower()
    if text[:2] in ("sh", "sz", "bj"):
        return text
    digits = text
    # 判断顺序有讲究：``9`` 开头同时覆盖沪市 B 股（900xxx）和北交所
    # （920xxx），必须先判 92 再判 9，否则北交所会被错划到沪市。
    if digits.startswith("92"):
        return "bj" + digits
    if digits.startswith(("8", "4")):
        return "bj" + digits
    if digits.startswith(("6", "9", "5")):
        return "sh" + digits
    if digits.startswith(("0", "1", "2", "3")):
        return "sz" + digits
    return "sh" + digits


def short_code(sina_symbol: str) -> str:
    """``sh600519`` → ``600519``。"""
    return sina_symbol[-6:] if len(sina_symbol) >= 6 else sina_symbol


def market_label(sina_symbol: str) -> str:
    return {"sh": "沪", "sz": "深", "bj": "北"}.get(sina_symbol[:2].lower(), "")


def is_index_symbol(sina_symbol: str) -> bool:
    """判断是不是指数。

    注意不能按 6 位代码判断：``sh000001`` 是上证指数，而 ``sz000001`` 是平安银行，
    同一个数字在不同市场含义完全不同。必须带上市场前缀一起看。
    指数的编码规律是沪市 ``sh000xxx``、深市 ``sz399xxx``、北交所 ``bj899xxx``。
    """
    text = sina_symbol.strip().lower()
    return text.startswith(("sh000", "sz399", "bj899"))


# --------------------------------------------------------------------------- #
# 数据源 1：hq.sinajs.cn 的 GBK 文本
# --------------------------------------------------------------------------- #
def parse_sina_quotes(text: str) -> dict[str, list[str]]:
    """把 ``var hq_str_sh600519="...";`` 解析成 ``{symbol: [字段...]}``。"""
    out: dict[str, list[str]] = {}
    for match in _SINA_LINE.finditer(text):
        body = match.group(2).strip()
        if body:
            out[match.group(1)] = body.split(",")
    return out


def quote_fields(fields: list[str]) -> dict[str, object]:
    """按位置解析新浪行情字段。

    位置是固定的，且**指数和个股的 0–9 位含义一致**：
    0 名称、1 今开、2 昨收、3 当前价、4 最高、5 最低、
    6 买一价、7 卖一价、8 成交量（股）、9 成交额（元）。
    日期与时间在尾部，但指数和个股的位置不一样，所以用正则找而不是按索引取。
    """
    def at(index: int) -> str | None:
        return fields[index] if len(fields) > index else None

    price = parse_number(at(3))
    prev_close = parse_number(at(2))
    change = None
    change_pct = None
    if price is not None and prev_close:
        change = round(price - prev_close, 4)
        change_pct = round(change / prev_close * 100, 4)

    stamp = ""
    for item in fields:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", item.strip()):
            stamp = item.strip()
            break
    for index, item in enumerate(fields):
        if re.fullmatch(r"\d{2}:\d{2}:\d{2}", item.strip()):
            stamp = f"{stamp} {item.strip()}".strip()
            break

    return {
        "name": (at(0) or "").strip(),
        "open": parse_number(at(1)),
        "prev_close": prev_close,
        "price": price,
        "high": parse_number(at(4)),
        "low": parse_number(at(5)),
        "volume": parse_number(at(8)),
        "amount": parse_number(at(9)),
        "change": change,
        "change_pct": change_pct,
        "timestamp": stamp,
    }


# --------------------------------------------------------------------------- #
# 数据源 2/3：新浪的 JSON 与 JS 对象
# --------------------------------------------------------------------------- #
def parse_json_array(text: str) -> list[dict]:
    """解析 ``Market_Center.getHQNodeData`` 返回的 JSON 数组。"""
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    return data if isinstance(data, list) else []


def parse_js_object(text: str) -> dict[str, str]:
    """解析 ``var X = {...};`` 形式的 JS 对象（值是字符串）。"""
    match = _JS_OBJECT.search(text.strip())
    if not match:
        return {}
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# 展示格式化
# --------------------------------------------------------------------------- #
def orderbook_fields(fields: list[str]) -> dict[str, list[list[float]]]:
    """解析买卖五档盘口。

    个股行情里第 10–29 位就是五档，**量、价成对出现**：

        10 买一量 | 11 买一价 | 12 买二量 | 13 买二价 | …… 18 买五量 | 19 买五价
        20 卖一量 | 21 卖一价 | ……                          28 卖五量 | 29 卖五价

    也就是说这份数据一直都在我们每次抓行情时返回的字段里，只是以前丢掉了，
    不需要为了盘口多抓一次。指数没有这一段，返回空列表。
    """
    def number(index: int) -> float | None:
        return parse_number(fields[index]) if len(fields) > index else None

    bids: list[list[float]] = []
    asks: list[list[float]] = []
    for level in range(5):
        bid_price = number(11 + level * 2)
        ask_price = number(21 + level * 2)
        if bid_price:
            bids.append([bid_price, number(10 + level * 2) or 0.0])
        if ask_price:
            asks.append([ask_price, number(20 + level * 2) or 0.0])
    return {"bids": bids, "asks": asks}


def macro_fields(symbol: str, fields: list[str]) -> dict[str, object]:
    """解析环球市场行情。

    新浪对这几类品种用了**四套完全不同的字段布局**，而且都是按位置取的，
    没有字段名。下面每一段注释都标了实测的字段位置，改的时候照着对：

    **外盘期货（``hf_`` 前缀）**——黄金、原油、伦铜、海外股指期货::

        0 现价 | 4 最高 | 5 最低 | 6 时间 | 7 昨收 | 8 今开 | 12 日期 | 13 名称

    **国内期货（``nf_`` 前缀）**——上期所的沪金、沪银、沪铜、螺纹钢::

        0 名称 | 1 时间 | 2 今开 | 3 最高 | 4 最低 | 8 最新价 | 10 昨结算 | 17 日期

    国内期货是最容易踩坑的一套：第 5 位叫「昨收盘」，但期货**没有收盘价**，
    这一位恒为 ``0.000``；真正的参考价是第 10 位「昨结算」。要是拿别的布局
    去套，很容易把「今日最高」当成基准，涨跌幅直接算反方向。

    **外汇即期（``fx_s`` 前缀）**——自带涨跌幅，不用自己算::

        0 时间 | 3 昨收 | 6 最高 | 7 最低 | 8 现价 | 9 名称 | 10 涨跌幅% | 11 涨跌额

    **简化版**——美元指数（``DINIW``）走的是这一套，没有涨跌幅字段::

        0 时间 | 3 昨收 | 6 最高 | 7 最低 | 8 现价 | 9 名称 | 末位 日期
    """

    def at(index: int) -> str | None:
        return fields[index] if len(fields) > index else None

    if symbol.lower().startswith("hf_"):
        price = parse_number(at(0))
        prev_close = parse_number(at(7))
        return {
            "name": (at(13) or "").strip(),
            "price": price,
            "prev_close": prev_close,
            "open": parse_number(at(8)),
            "high": parse_number(at(4)),
            "low": parse_number(at(5)),
            "time": (at(6) or "").strip(),
            "date": (at(12) or "").strip(),
        }

    if symbol.lower().startswith("nf_"):
        return {
            "name": (at(0) or "").strip(),
            "price": parse_number(at(8)),
            "prev_close": parse_number(at(10)),
            "open": parse_number(at(2)),
            "high": parse_number(at(3)),
            "low": parse_number(at(4)),
            "time": _compact_clock(at(1)),
            "date": (at(17) or "").strip(),
        }

    # 外汇：第 10/11 位直接给了涨跌幅与涨跌额，比自己算更准
    has_change = symbol.lower().startswith("fx_s")
    last = fields[-1].strip() if fields else ""
    return {
        "name": (at(9) or "").strip(),
        "price": parse_number(at(8)),
        "prev_close": parse_number(at(3)),
        "high": parse_number(at(6)),
        "low": parse_number(at(7)),
        "change": parse_number(at(11)) if has_change else None,
        "change_pct": parse_number(at(10)) if has_change else None,
        "time": (at(0) or "").strip(),
        "date": last if re.fullmatch(r"\d{4}-\d{2}-\d{2}", last) else "",
    }


def _compact_clock(raw: str | None) -> str:
    """国内期货的时间是 ``000645`` 这种无分隔写法，补成 ``00:06:45``。

    长度对不上就原样返回——这里只做美化，不该因为格式意外就丢掉信息。
    """
    text = (raw or "").strip()
    if len(text) == 6 and text.isdigit():
        return f"{text[0:2]}:{text[2:4]}:{text[4:6]}"
    return text


def digits_for(price: float | None) -> int:
    """按量级决定小数位。

    美元人民币是 6.7065（要 4 位才看得出变化），黄金是 4362.56（2 位就够）。
    统一用一个格式会让汇率看起来像一潭死水。
    """
    if price is None:
        return 2
    if abs(price) < 10:
        return 4
    if abs(price) < 100:
        return 3
    return 2


def format_money(value: float | None) -> str:
    """把元换算成中文习惯的量级：1.23 万亿 / 45.6 亿 / 789.0 万。"""
    if value is None:
        return "—"
    abs_value = abs(value)
    if abs_value >= 1e12:
        return f"{value / 1e12:.2f} 万亿"
    if abs_value >= 1e8:
        return f"{value / 1e8:.2f} 亿"
    if abs_value >= 1e4:
        return f"{value / 1e4:.1f} 万"
    return f"{value:,.0f}"


def format_shares(value: float | None) -> str:
    """成交量按「手」展示更符合 A 股习惯（1 手 = 100 股）。"""
    if value is None:
        return "—"
    hands = value / 100
    if hands >= 1e8:
        return f"{hands / 1e8:.2f} 亿手"
    if hands >= 1e4:
        return f"{hands / 1e4:.1f} 万手"
    return f"{hands:,.0f} 手"
