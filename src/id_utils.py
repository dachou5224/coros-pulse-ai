"""
Activity ID 规范化与表头列定位。
main / activity_advice 共用，避免「按表头读 DataFrame、却按 A 列写 Sheet」导致点评错位。
"""
from __future__ import annotations

import re

import pandas as pd


def normalize_activity_id(val) -> str:
    """
    统一 int / float / str / 科学计数法 等形式的 Strava Activity ID 为纯数字字符串。
    对已是纯数字的字符串不再经 float，避免大整数超过 2^53 时精度丢失。
    """
    if val is None:
        return ""
    try:
        if isinstance(val, float) and pd.isna(val):
            return ""
    except Exception:
        pass
    if isinstance(val, bool):
        return str(int(val))
    if isinstance(val, int):
        return str(val)

    s = str(val).strip()
    if not s:
        return ""

    if re.fullmatch(r"\d+", s):
        return s
    m = re.fullmatch(r"(\d+)\.0+", s)
    if m:
        return m.group(1)

    if re.search(r"[eE]", s):
        try:
            from decimal import Decimal, InvalidOperation

            d = Decimal(s)
            if d == d.to_integral_value():
                return format(int(d), "d")
        except (InvalidOperation, ValueError, OverflowError):
            pass

    try:
        f = float(s)
        if f != f:  # NaN
            return ""
        if abs(f) < 2**53 and f == int(f):
            return str(int(f))
    except (ValueError, TypeError, OverflowError):
        pass

    return s


def activity_id_column_index(headers: list) -> tuple[int, bool]:
    """
    在表头行中定位「Activity ID」列（0-based）。
    返回 (index, found)。未找到时回退 0，found=False（兼容旧表但建议修正表头）。
    """
    if not headers:
        return 0, False
    for i, h in enumerate(headers):
        if h is not None and str(h).strip() == "Activity ID":
            return i, True
    return 0, False
