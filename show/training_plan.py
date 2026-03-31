"""
夏训五期：读取 data/training/plan.json + docs/summer_training_plan_5phases.html，
与周报 DataFrame 对齐，供 Streamlit 展示计划与执行进度。
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

_SHOW_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SHOW_DIR.parent

_ROOT_CSS_FALLBACK = """
:root {
  --color-background-primary: #ffffff;
  --color-background-secondary: #f3f4f6;
  --color-border-tertiary: #e5e7eb;
  --color-text-primary: #111827;
  --color-text-secondary: #4b5563;
  --color-text-tertiary: #9ca3af;
  --border-radius-md: 8px;
}
"""


def repo_root() -> Path:
    return _REPO_ROOT


def load_plan() -> dict[str, Any]:
    path = _REPO_ROOT / "data" / "training" / "plan.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def summer_plan_html_fragment() -> str:
    """含 :root 兜底的 HTML 片段，供 st.markdown(..., unsafe_allow_html=True)。"""
    src = _REPO_ROOT / "docs" / "summer_training_plan_5phases.html"
    raw = src.read_text(encoding="utf-8")
    if "<style>" in raw:
        body = raw.replace("<style>", "<style>" + _ROOT_CSS_FALLBACK, 1)
    else:
        body = _ROOT_CSS_FALLBACK + raw
    return body


def _strip_html(raw: str) -> str:
    text = raw.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+\n", "\n", html.unescape(text)).strip()


def load_phase_playbook() -> dict[str, dict[str, Any]]:
    """
    从 docs/summer_training_plan_5phases.html 提取每一期的展示信息，
    用于在前端做“周报 vs 计划”的追踪和跟进建议。
    """
    src = _REPO_ROOT / "docs" / "summer_training_plan_5phases.html"
    raw = src.read_text(encoding="utf-8")
    blocks = re.findall(r"(<!--\s*Phase\s+\d+:[\s\S]*?)(?=<!--\s*Phase\s+\d+:|<script>|$)", raw)
    playbook: dict[str, dict[str, Any]] = {}
    for block in blocks:
        phase_id_m = re.search(r'id="(p\d)"', block)
        if not phase_id_m:
            continue
        phase_id = phase_id_m.group(1)
        stats = {
            _strip_html(k): _strip_html(v)
            for k, v in re.findall(r'<div class="pl">([\s\S]*?)</div><div class="pv">([\s\S]*?)</div>', block)
        }
        week_cards = []
        for day, title, detail in re.findall(
            r'<div class="wdl">([\s\S]*?)</div><div class="wdt"[^>]*>([\s\S]*?)</div><div class="wds">([\s\S]*?)</div>',
            block,
        ):
            week_cards.append(
                {
                    "day": _strip_html(day),
                    "title": _strip_html(title),
                    "detail": _strip_html(detail),
                }
            )
        key_items = []
        for tag, desc in re.findall(r'<span class="kt"[^>]*>([\s\S]*?)</span>\s*<div class="kd">([\s\S]*?)</div>', block):
            key_items.append({"tag": _strip_html(tag), "description": _strip_html(desc)})
        note_m = re.search(r'<div class="note"[^>]*>([\s\S]*?)</div>', block)
        playbook[phase_id] = {
            "stats": stats,
            "week_cards": week_cards,
            "key_items": key_items,
            "note": _strip_html(note_m.group(1)) if note_m else "",
        }
    return playbook


def _parse_iso(d: str) -> date:
    return datetime.strptime(d.strip(), "%Y-%m-%d").date()


def phase_for_week_end(week_end: date, phases: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    for ph in phases:
        s = _parse_iso(ph["start"])
        e = _parse_iso(ph["end"])
        if s <= week_end <= e:
            return ph
    return None


def current_phase_message(today: date, plan: dict[str, Any]) -> str:
    phases = plan["phases"]
    for ph in phases:
        s = _parse_iso(ph["start"])
        e = _parse_iso(ph["end"])
        if s <= today <= e:
            return (
                f"今天 **{today.isoformat()}** 落在「{ph['name']}」"
                f"（{ph['start']} ~ {ph['end']}）。"
            )
    return f"今天 **{today.isoformat()}** 不在夏训五期日期范围内。"


def _status_label(actual: Optional[float], lo: float, hi: float) -> str:
    if actual is None:
        return "无数据"
    if actual < lo:
        return "低于计划"
    if actual > hi:
        return "高于计划"
    return "在区间内"


def build_progress_dataframe(df: pd.DataFrame, plan: dict[str, Any]) -> pd.DataFrame:
    """
    仅保留 Week End 落在某一计划期内的周报行；以实际周跑量对比当期 min/max。
    """
    cmap = plan.get("csv_column_map") or {}
    col_ws = cmap.get("week_start", "Week Start")
    col_we = cmap.get("week_end", "Week End")
    col_dist = cmap.get("distance_km", "Distance (km)")
    phases: list[dict[str, Any]] = plan["phases"]

    for c in (col_ws, col_we, col_dist):
        if c not in df.columns:
            raise ValueError(f"CSV 缺少列「{c}」。现有列：{list(df.columns)}")

    work = df.copy()
    work[col_ws] = pd.to_datetime(work[col_ws])
    work[col_we] = pd.to_datetime(work[col_we])
    work[col_dist] = work[col_dist].astype(str).str.replace(",", "", regex=False)
    work[col_dist] = pd.to_numeric(work[col_dist], errors="coerce")
    work = work.sort_values(col_ws, ascending=True)

    rows: list[dict[str, Any]] = []
    for _, row in work.iterrows():
        we = row[col_we]
        if pd.isna(we):
            continue
        week_end = we.date() if hasattr(we, "date") else pd.to_datetime(we).date()
        ph = phase_for_week_end(week_end, phases)
        if ph is None:
            continue
        ws = row[col_ws]
        week_start_s = ws.strftime("%Y-%m-%d") if hasattr(ws, "strftime") else str(ws)[:10]
        dist = row[col_dist]
        actual = float(dist) if not pd.isna(dist) else None
        lo = float(ph["planned_week_km_min"])
        hi = float(ph["planned_week_km_max"])
        rows.append(
            {
                "周起始": week_start_s,
                "周结束": week_end.isoformat(),
                "所属期": ph["name"],
                "计划周跑量 (km)": f"{lo:.0f}–{hi:.0f}",
                "实际 (km)": round(actual, 1) if actual is not None else None,
                "状态": _status_label(actual, lo, hi),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["周起始", "周结束", "所属期", "计划周跑量 (km)", "实际 (km)", "状态"]
        )

    return pd.DataFrame(rows)


def phase_week_counts(df: pd.DataFrame, plan: dict[str, Any]) -> dict[str, int]:
    """各计划期内出现的周报行数（Week End 归属）。"""
    cmap = plan.get("csv_column_map") or {}
    col_we = cmap.get("week_end", "Week End")
    phases = plan["phases"]
    counts = {ph["id"]: 0 for ph in phases}
    for _, row in df.iterrows():
        we = row[col_we]
        if pd.isna(we):
            continue
        week_end = we.date() if hasattr(we, "date") else pd.to_datetime(we).date()
        ph = phase_for_week_end(week_end, phases)
        if ph:
            counts[ph["id"]] += 1
    return counts


def resolve_reference_phase(week_end: date, plan: dict[str, Any]) -> tuple[dict[str, Any], str]:
    phases = plan["phases"]
    current = phase_for_week_end(week_end, phases)
    if current:
        return current, "in_phase"

    first = phases[0]
    last = phases[-1]
    first_start = _parse_iso(first["start"])
    last_end = _parse_iso(last["end"])
    if week_end < first_start:
        return first, "before_plan"
    if week_end > last_end:
        return last, "after_plan"

    for ph in phases:
        if week_end < _parse_iso(ph["start"]):
            return ph, "before_phase"
    return last, "after_plan"


def build_phase_follow_up(latest_week: pd.Series, plan: dict[str, Any], playbook: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """
    把最新周报与训练计划做对照，生成可直接展示在前端侧栏的追踪卡片。
    """
    week_end = latest_week.get("Week End")
    if pd.isna(week_end):
        raise ValueError("latest_week 缺少 Week End")
    week_end_date = week_end.date() if hasattr(week_end, "date") else pd.to_datetime(week_end).date()
    phase, relation = resolve_reference_phase(week_end_date, plan)
    details = playbook.get(phase["id"], {})

    actual_km = float(latest_week.get("Distance (km)") or 0)
    lo = float(phase["planned_week_km_min"])
    hi = float(phase["planned_week_km_max"])
    gap_low = round(actual_km - lo, 1)
    gap_high = round(actual_km - hi, 1)
    volume_status = _status_label(actual_km, lo, hi)

    relation_text = {
        "in_phase": f"本周已落在「{phase['name']}」",
        "before_plan": f"当前周报早于计划起点，先对照即将开始的「{phase['name']}」",
        "before_phase": f"当前周报早于「{phase['name']}」，可提前按该期目标做衔接",
        "after_plan": f"当前周报已晚于计划末期，以下按最后一期「{phase['name']}」复盘",
    }.get(relation, phase["name"])

    tsb = float(latest_week.get("Form (TSB)") or 0)
    decouple = float(latest_week.get("LSD Decouple") or 0)
    follow_ups = []
    if volume_status == "低于计划":
        follow_ups.append(f"周跑量还差 {abs(gap_low):.1f} km 才到本期下限，先把总量补到 {lo:.0f} km 再谈强度。")
    elif volume_status == "高于计划":
        follow_ups.append(f"本周已超出本期上限 {abs(gap_high):.1f} km，下周优先控量，避免把计划周跑量当成日常下限。")
    else:
        follow_ups.append(f"本周跑量落在计划区间 {lo:.0f}–{hi:.0f} km，可继续按本期结构推进。")

    if tsb < -20:
        follow_ups.append("TSB 已进入高疲劳区，下周先保证 1-2 天真正轻松跑或休息，再上关键课。")
    elif tsb > 10:
        follow_ups.append("TSB 偏高，说明身体较新鲜，可把本期关键课跑完整，但不要额外加码。")

    if decouple > 5:
        follow_ups.append("LSD 解耦偏高，长跑当天先守心率红线，再考虑配速，不要把有氧长跑跑成测试课。")

    key_items = details.get("key_items") or []
    return {
        "phase": phase,
        "relation_text": relation_text,
        "volume_status": volume_status,
        "target_weekly_km": f"{lo:.0f}–{hi:.0f} km",
        "actual_weekly_km": round(actual_km, 1),
        "long_run_target": (
            f"{phase['long_run_km_min']:.0f}–{phase['long_run_km_max']:.0f} km"
            if phase.get("long_run_km_min") is not None and phase.get("long_run_km_max") is not None
            else "按减量周状态灵活安排"
        ),
        "stats": details.get("stats", {}),
        "week_cards": details.get("week_cards", []),
        "key_items": key_items,
        "note": details.get("note", ""),
        "follow_ups": follow_ups,
    }
