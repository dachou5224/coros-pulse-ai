"""
单次跑步教练点评：独立脚本，对最近 N 条尚未有点评的活动生成 AI 点评，
解析五段（总评、配速、心率、步频与爬升、下次训练课）写入 sheet1；
并写入「点评更新时间(UTC)」列，便于与历史点评区分。
可单独运行，便于接入 GitHub Actions workflow。
"""
import re
import os
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import gspread
from gspread.exceptions import APIError
from gspread.utils import rowcol_to_a1
from oauth2client.service_account import ServiceAccountCredentials

# 确保可导入 coach
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

try:
    from coach import get_activity_advice
    import coach as _coach
except ImportError:
    get_activity_advice = None
    _coach = None

from id_utils import activity_id_column_index, normalize_activity_id

JSON_KEY = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON")
SHEET_NAME = "Coros_Running_Data"

ADVICE_SLOTS = ["总评", "配速", "心率", "步频与爬升", "下次训练课"]
# 每次成功写入点评时更新，便于与历史点评区分（旧行无时间或时间为更早）
META_COL = "点评更新时间(UTC)"
ALL_ADVICE_HEADERS = ADVICE_SLOTS + [META_COL]
# 连续请求 Gemini 间隔（秒），减轻 Connection error；环境变量设为 0 可关闭
_ADVICE_LOOP_DELAY = float(os.getenv("ACTIVITY_ADVICE_DELAY_SECONDS") or "1.25")

# #region agent log
_REPO_ROOT = Path(__file__).resolve().parent.parent
_AGENT_LOG = os.environ.get(
    "DEBUG_NDJSON_LOG",
    str(_REPO_ROOT.parent / ".cursor" / "debug-deb334.log"),
)


def _agent_dbg(message: str, hypothesis_id: str, data=None):
    """调试会话 deb334：写入 NDJSON，不含密钥/PII。"""
    try:
        payload = {
            "sessionId": "deb334",
            "location": "activity_advice.py",
            "message": message,
            "hypothesisId": hypothesis_id,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
        }
        with open(_AGENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


# #endregion


def get_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if not JSON_KEY:
        print("❌ 错误：未找到 Google Credentials Secret")
        return None
    try:
        creds_dict = json.loads(JSON_KEY)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        return gspread.authorize(creds)
    except Exception as e:
        print(f"❌ 认证失败: {e}")
        return None


def _retry_gspread_write(fn, *, max_attempts=6):
    """Sheets 写限流 (429) 时指数退避重试。"""
    for attempt in range(max_attempts):
        try:
            return fn()
        except APIError as e:
            err = str(e)
            if "429" in err and attempt < max_attempts - 1:
                wait = min(60, 2**attempt)
                print(f"⏳ Sheets API 限流 (429)，{wait}s 后重试 ({attempt + 1}/{max_attempts})...")
                time.sleep(wait)
                continue
            raise


def _write_advice_slots_batch(
    worksheet, row_num: int, col_indices: dict, slots: dict, *, utc_stamp: str
) -> None:
    """单行五段点评 + 可选时间戳列，一次 values_batchUpdate。"""
    data = []
    for tag in ADVICE_SLOTS:
        col = col_indices[tag]
        r = rowcol_to_a1(row_num, col)
        data.append({"range": r, "values": [[slots.get(tag, "")]]})
    if META_COL in col_indices:
        mc = col_indices[META_COL]
        data.append({"range": rowcol_to_a1(row_num, mc), "values": [[utc_stamp]]})

    def _do():
        return worksheet.batch_update(data)

    _retry_gspread_write(_do)


def _build_activity_id_to_row(all_values: list, id_col_idx: int) -> dict:
    """
    从 sheet 原始行构建「规范化 Activity ID -> 1-based 行号」。
    同一 ID 多行时保留最后一次出现的行（通常对应最新排序下的有效行）。
    id_col_idx：表头中「Activity ID」列的 0-based 索引（勿硬编码 A 列）。
    """
    id_to_row: dict[str, int] = {}
    duplicates: list[tuple[str, int, int]] = []
    for row_num, row in enumerate(all_values[1:], start=2):
        if not row:
            continue
        raw = row[id_col_idx] if len(row) > id_col_idx else ""
        aid = normalize_activity_id(raw)
        if not aid:
            continue
        if aid in id_to_row:
            duplicates.append((aid, id_to_row[aid], row_num))
        id_to_row[aid] = row_num
    if duplicates:
        for aid, r_old, r_new in duplicates[:5]:
            print(f"⚠️ Activity ID 在表格中重复: {aid}（先前第 {r_old} 行，现用第 {r_new} 行）")
        if len(duplicates) > 5:
            print(f"⚠️ … 另有 {len(duplicates) - 5} 组重复 ID，均已以后出现行为准")
    return id_to_row


def _parse_advice_slots(raw: str) -> dict:
    """从 coach 输出中按【标签】提取五段。"""
    slots = {}
    for tag in ADVICE_SLOTS:
        m = re.search(rf"【{re.escape(tag)}】\s*(.*?)(?=【|$)", raw, re.DOTALL)
        slots[tag] = (m.group(1).strip() if m else "")[:50000]
    return slots


def main():
    print("🚀 开始执行单次跑步教练点评...")
    _agent_dbg("activity_advice main 开始", "H0", {"argv0": sys.argv[0] if sys.argv else ""})
    if not get_activity_advice:
        print("❌ 无法导入 coach.get_activity_advice")
        _agent_dbg("coach 导入失败", "H1", {})
        return 1

    client = get_client()
    if not client:
        _agent_dbg("get_client 失败", "H2", {"has_json_key": bool(JSON_KEY and str(JSON_KEY).strip())})
        return 1

    try:
        sh = client.open(SHEET_NAME)
    except Exception as e:
        print(f"❌ 找不到表格 '{SHEET_NAME}': {e}")
        _agent_dbg("打开表格失败", "H3", {"error_type": type(e).__name__})
        return 1

    # 读取 Activities
    activities_ws = sh.sheet1
    df = pd.DataFrame(activities_ws.get_all_records())
    if df.empty:
        print("❌ Activities 表无数据")
        _agent_dbg("Activities 空表", "H4", {"row_count_hint": activities_ws.row_count})
        return 1
    if "Activity ID" in df.columns:
        df["Activity ID"] = df["Activity ID"].map(normalize_activity_id)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.sort_values("Date")

    # 读取最新周报作 weekly_context
    report_row_dict = {}
    try:
        rpt_ws = sh.worksheet("Weekly_Report")
        rpt_records = rpt_ws.get_all_records()
        if rpt_records:
            by_week = sorted(rpt_records, key=lambda r: (r.get("Week Start") or r.get("Week End") or ""))
            last = by_week[-1]
            report_row_dict = {
                "Fitness (CTL)": last.get("Fitness (CTL)"),
                "Form (TSB)": last.get("Form (TSB)"),
                "VDOT": last.get("VDOT"),
            }
    except gspread.WorksheetNotFound:
        pass

    # 准备点评列 + 时间戳列表头（时间列在点评列右侧）
    headers = activities_ws.row_values(1)
    id_col_idx, id_hdr_ok = activity_id_column_index(headers)
    if not id_hdr_ok:
        print(
            "⚠️ 表头第 1 行未找到「Activity ID」，已回退使用第 A 列做行映射；"
            "若插入过列，请修正表头以免点评写入错位。"
        )
    col_indices = {}
    next_col = len(headers) + 1
    for tag in ALL_ADVICE_HEADERS:
        if tag in headers:
            col_indices[tag] = headers.index(tag) + 1
        else:
            activities_ws.update_cell(1, next_col, tag)
            col_indices[tag] = next_col
            next_col += 1
    print(
        f"📌 表头已就绪：点评列 {len(ADVICE_SLOTS)} 个；"
        f"「{META_COL}」列用于标记本次写入时间，便于与旧点评区分。"
    )

    # LLM：无密钥时 coach 静默返回空串，易被误认为「脚本没跑」——此处明确提示（尤其 GitHub Actions）
    _has_llm = bool(_coach and getattr(_coach, "API_KEY", "").strip())
    if not _has_llm:
        print(
            "⚠️ LLM 未配置：环境变量中无 API_KEY / GEMINI_API_KEY / GOOGLE_API_KEY，"
            "单次跑步点评不会生成。请在仓库 Settings → Secrets → Actions 中配置 API_KEY 或 GEMINI_API_KEY。"
        )
    else:
        print(
            f"🤖 LLM 已配置（模型 {_coach.MODEL}），将对「最近 N 条里尚未有总评」的活动请求点评。"
        )

    # 去重：已有「总评」的跳过
    all_values = activities_ws.get_all_values()
    existing_ids = set()
    col_zongping = col_indices.get("总评")
    if col_zongping and len(all_values) > 1:
        for i, row in enumerate(all_values[1:], start=2):
            if len(row) >= col_zongping:
                val = row[col_zongping - 1]
                if val and str(val).strip():
                    cell_id = row[id_col_idx] if len(row) > id_col_idx else ""
                    aid = normalize_activity_id(cell_id)
                    if aid:
                        existing_ids.add(aid)

    # 按「Activity ID」列（非硬编码 A 列）建立 ID -> 行号
    id_to_row = _build_activity_id_to_row(all_values, id_col_idx)

    # 最近 limit 条（默认 20；本地/调试可设 ACTIVITY_ADVICE_LIMIT=5）
    limit = max(1, min(100, int(os.getenv("ACTIVITY_ADVICE_LIMIT", "20"))))
    recent = df.tail(limit)
    weekly_context = report_row_dict
    appended = 0

    pending_ids: list[str] = []
    for _ix in range(len(recent)):
        _aid = normalize_activity_id(recent.iloc[_ix].get("Activity ID", ""))
        if _aid and _aid not in existing_ids:
            pending_ids.append(_aid)
    print(
        f"📊 扫描范围：时间序最后 {limit} 条；其中「总评」为空、待尝试 LLM 的活动：{len(pending_ids)} 条。"
    )
    if pending_ids and len(pending_ids) <= 10:
        print(f"   待处理 Activity ID: {', '.join(pending_ids)}")
    elif pending_ids:
        print(f"   待处理示例（前 5 个）: {', '.join(pending_ids[:5])} …")

    for idx in range(len(recent) - 1, -1, -1):
        row = recent.iloc[idx]
        aid = normalize_activity_id(row.get("Activity ID", ""))
        if not aid or aid in existing_ids:
            continue

        start_idx = max(0, idx - 4)
        recent_activities = [recent.iloc[i] for i in range(start_idx, idx + 1)]

        try:
            advice_text = get_activity_advice(
                row, recent_activities=recent_activities, weekly_context=weekly_context
            ) or ""
        except Exception as e:
            print(f"⚠️ 单条点评失败 Activity {aid}: {e}")
            advice_text = ""
        finally:
            if _ADVICE_LOOP_DELAY > 0:
                time.sleep(_ADVICE_LOOP_DELAY)

        slots = _parse_advice_slots(advice_text)
        # 新 prompt 口语化输出无【标签】，解析为空时用 raw 写入总评
        if not any(slots.get(t) for t in ADVICE_SLOTS) and advice_text:
            slots["总评"] = advice_text[:50000]

        if not any((slots.get(t) or "").strip() for t in ADVICE_SLOTS):
            print(f"  ⏭ 跳过 Activity {aid}：LLM 无有效输出，不覆盖表格")
            continue

        sheet_row = id_to_row.get(aid)
        if sheet_row is None:
            print(f"⚠️ 表格「Activity ID」列未找到行 ID={aid}，跳过写入（请检查是否与 Sheet 中该列一致）")
            _agent_dbg("sheet row missing for id", "H6", {"aid_len": len(aid)})
            continue
        # 写入前用缓存的 all_values 再确认该行 A 列与 aid 一致（避免额外 API，且与映射同源）
        row_vals = all_values[sheet_row - 1] if 1 <= sheet_row <= len(all_values) else []
        id_raw = row_vals[id_col_idx] if len(row_vals) > id_col_idx else ""
        if normalize_activity_id(id_raw) != aid:
            col_letter = "A" if id_col_idx == 0 else f"列索引{id_col_idx}"
            print(
                f"⚠️ 行 {sheet_row} {col_letter}（Activity ID 列）与期望 ID={aid} 不一致（当前: {id_raw!r}），跳过写入"
            )
            _agent_dbg("row A1 mismatch", "H6", {"sheet_row": sheet_row})
            continue
        try:
            utc_stamp_cell = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            _write_advice_slots_batch(
                activities_ws, sheet_row, col_indices, slots, utc_stamp=utc_stamp_cell
            )
            existing_ids.add(aid)
            appended += 1
            preview = (slots.get("总评") or "").replace("\n", " ").strip()
            if len(preview) > 80:
                preview = preview[:80] + "…"
            log_extra = ""
            if os.getenv("GITHUB_RUN_ID"):
                log_extra = f" | GitHub run {os.getenv('GITHUB_RUN_ID')}"
            print(f"  ✓ 行 {sheet_row} | Activity ID={aid} | {META_COL}: {utc_stamp_cell}{log_extra}")
            print(f"      总评预览: {preview or '(空)'}")
        except APIError as e:
            print(f"⚠️ 写入活动 {aid} 失败: {e}")
            _agent_dbg("sheets APIError", "H5", {"error_type": type(e).__name__})

    if appended > 0:
        print(f"✅ 单次跑步教练点评已写入 {appended} 条")
    else:
        print("✅ 本次未写入新的单次点评（可能：均已有点评、无待处理活动、LLM 未配置或调用失败）")
        if not _has_llm and pending_ids:
            print(
                "   原因提示：已发现待点评活动，但缺少 API_KEY / GEMINI_API_KEY，请配置 Secrets 后重跑 workflow。"
            )
        elif _has_llm and pending_ids:
            print(
                "   原因提示：有待处理 ID，但 LLM 返回为空或写入校验未通过；请向上翻看 ⚠️ 行。"
            )

    _agent_dbg("activity_advice 正常结束", "H0", {"appended": appended})
    return 0


if __name__ == "__main__":
    sys.exit(main())
