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

_SINA_LINE = re.compile(r'var\s+hq_str_([a-z]{2}\d{6})="([^"]*)"')
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
