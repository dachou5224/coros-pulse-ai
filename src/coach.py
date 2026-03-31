"""
教练点评模块：使用 OpenAI 兼容方式调用 Google Gemini，生成本周教练点评与单次跑步点评。
与 my-tech-blog / wechat-to-xhs 的调用方式一致。
"""
import os
import time
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

try:
    import httpx

    _OPENAI_TIMEOUT = httpx.Timeout(120.0, connect=45.0, read=120.0, write=45.0, pool=45.0)
except Exception:
    httpx = None  # type: ignore
    _OPENAI_TIMEOUT = 120.0

try:
    from openai import APIConnectionError, APITimeoutError, RateLimitError

    _OPENAI_TRANSIENT_EXC = (APIConnectionError, APITimeoutError, RateLimitError)
except ImportError:
    _OPENAI_TRANSIENT_EXC = ()

# 从项目根加载 .env（与 analysis 等脚本一致，可被 CI 环境变量覆盖）
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

_RAW_API_KEY = (os.getenv("API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
# 仅保留 ASCII：密钥中若混入全角/不可见字符，会导致 httpx 在编码请求头或 URL 时触发 ascii 错误
API_KEY = "".join(c for c in _RAW_API_KEY if ord(c) < 128).strip()
_RAW_BASE_URL = (os.getenv("BASE_URL") or "").strip()
BASE_URL = (
    "".join(c for c in _RAW_BASE_URL if ord(c) < 128).strip()
    if _RAW_BASE_URL
    else ""
) or "https://generativelanguage.googleapis.com/v1beta/openai"
_RAW_MODEL = (os.getenv("COACH_MODEL") or os.getenv("MODEL_NAME") or "gemini-2.0-flash").strip()
MODEL = "".join(c for c in _RAW_MODEL if ord(c) < 128).strip() or "gemini-2.0-flash"
LLM_DELAY_SECONDS = float((os.getenv("LLM_DELAY_SECONDS") or "").strip() or "0")
LLM_MAX_ATTEMPTS = max(1, min(12, int((os.getenv("LLM_MAX_ATTEMPTS") or "6").strip() or "6")))

RUNNER_GENDER = os.getenv("RUNNER_GENDER", "").strip()
RUNNER_AGE_RAW = os.getenv("RUNNER_AGE", "").strip()
RUNNER_AGE = int(RUNNER_AGE_RAW) if RUNNER_AGE_RAW.isdigit() else None
RUNNER_GOAL_RACE = os.getenv("RUNNER_GOAL_RACE", "半马/全马").strip()
RUNNER_GOAL_TIME = os.getenv("RUNNER_GOAL_TIME", "未设定").strip()
RUNNER_INJURY_HISTORY = os.getenv("RUNNER_INJURY_HISTORY", "无").strip()

RUNNER_PROFILE = {
    "gender": RUNNER_GENDER or "未知",
    "age": RUNNER_AGE,
    "goal_race": RUNNER_GOAL_RACE,
    "goal_time": RUNNER_GOAL_TIME,
    "injury_history": RUNNER_INJURY_HISTORY,
}

# 全角标点 → 半角：避免在部分 Linux/CI 环境下 httpx 构建请求时出现 ascii 编码错误（如 \uff08）
_FW_PUNCT = str.maketrans(
    {
        "\uff08": "(",
        "\uff09": ")",
        "\uff0c": ",",
        "\uff1a": ":",
        "\uff1b": ";",
        "\uff01": "!",
        "\uff1f": "?",
    }
)


def _normalize_llm_text(s: str) -> str:
    """
    NFKC 将全角标点/兼容字符转为常规形式（如 U+FF08 → '('），再补全角标点表。
    解决 CI 上 httpx 对 URL/请求部分使用 ascii 编码时的 UnicodeEncodeError。
    """
    if not s:
        return s
    t = unicodedata.normalize("NFKC", s)
    return t.translate(_FW_PUNCT)


def _normalize_base_url(url: str) -> str:
    """统一去掉末尾斜线，避免与 SDK 拼接后出现双斜线导致 404。"""
    return (url or "").strip().rstrip("/")


def _is_gemini() -> bool:
    return "generativelanguage.googleapis.com" in (BASE_URL or "").lower() or "gemini" in (MODEL or "").lower()


def _is_transient_llm_error(e: BaseException) -> bool:
    """429 / 连接失败 / 超时 等可重试错误。"""
    if _OPENAI_TRANSIENT_EXC and isinstance(e, _OPENAI_TRANSIENT_EXC):
        return True
    err_msg = str(e).lower()
    if "429" in err_msg or "rate" in err_msg or "quota" in err_msg:
        return True
    if "connection error" in err_msg or "connection" in err_msg:
        return True
    if "timeout" in err_msg or "timed out" in err_msg:
        return True
    if "remote" in err_msg and ("closed" in err_msg or "reset" in err_msg):
        return True
    if "ssl" in err_msg or "tls" in err_msg:
        return True
    name = type(e).__name__.lower()
    if "timeout" in name or "connect" in name:
        return True
    return False


def _model_for_request() -> str:
    """模型名仅使用 ASCII，避免 httpx 在拼接 URL 时 raw_path.encode('ascii') 失败。"""
    try:
        MODEL.encode("ascii")
        return MODEL
    except UnicodeEncodeError:
        return "".join(c for c in MODEL if ord(c) < 128).strip() or "gemini-2.0-flash"


def _get_client():
    """返回 OpenAI 兼容客户端；未配置 API_KEY 时返回 None。"""
    if not API_KEY:
        return None
    base_url = _normalize_base_url(BASE_URL) or None
    base_safe = base_url
    if base_url:
        try:
            base_url.encode("ascii")
        except UnicodeEncodeError:
            base_safe = "".join(c for c in base_url if ord(c) < 128).strip() or "https://generativelanguage.googleapis.com/v1beta/openai"
    # max_retries=0：连接/429 由 _call_llm 统一退避，避免与 SDK 内置重试叠加
    return OpenAI(
        api_key=API_KEY,
        base_url=base_safe,
        max_retries=0,
        timeout=_OPENAI_TIMEOUT,
    )


def _call_llm(system: str, user: str, max_tokens: int = 600) -> str:
    """
    调用 LLM，返回纯文本。对 429 / Connection error / 超时 等做指数退避重试。
    """
    client = _get_client()
    if not client:
        return ""
    kwargs = {
        "model": _model_for_request(),
        "messages": [
            {"role": "system", "content": _normalize_llm_text(system)},
            {"role": "user", "content": _normalize_llm_text(user)},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "timeout": 120,
    }
    for attempt in range(LLM_MAX_ATTEMPTS):
        try:
            resp = client.chat.completions.create(**kwargs)
            raw = (resp.choices[0].message.content or "").strip()
            return raw if raw else ""
        except UnicodeEncodeError as e:
            print(f"⚠️ 教练点评 LLM 请求编码失败（UnicodeEncodeError）: {e}")
            return ""
        except Exception as e:
            if _is_transient_llm_error(e) and attempt < LLM_MAX_ATTEMPTS - 1:
                wait = min(60, 2**attempt + (0.5 if attempt else 0.0))
                print(
                    f"⚠️ 教练点评 LLM 暂发性失败 [{type(e).__name__}] {e!s}，{wait:.1f}s 后重试 "
                    f"({attempt + 1}/{LLM_MAX_ATTEMPTS})…"
                )
                time.sleep(wait)
                continue
            print(f"⚠️ 教练点评 LLM 调用失败: {e}")
            return ""
    return ""


def get_weekly_advice(weekly_activities_df, weekly_report_dict, recent_weeks_reports=None) -> str:
    """
    根据当周 Activities 与周报指标，生成「本周总结与下周建议」。
    weekly_activities_df: 当周跑步的 DataFrame（列含 Date, Name, Distance (km), Duration (min), Avg Pace, Avg HR 等）
    weekly_report_dict: 当周周报字典（含 Distance (km), Runs, Avg Pace, Weekly Load, Fitness (CTL), Form (TSB), VDOT, LSD Decouple, Status）
    recent_weeks_reports: 可选，近期 6–8 周周报列表（dict），按时间升序，用于推断训练季阶段与季长
    跑者画像自动从环境变量 RUNNER_* 读取，可在 .env 中配置。
    返回纯文本建议；失败返回空串。
    """
    system = (
        "你是一位资深马拉松教练，正在和你的学员做每周面对面复盘，时间只有5分钟，你需要说最重要的话。\n"
        "你看过他这周所有的跑步数据，你了解他的训练背景，不需要重复介绍他已经知道的东西。\n\n"

        "【说话风格】\n"
        "- 用'你'称呼学员，像对话而非报告\n"
        "- 禁止使用 ### 标题、禁止用 * 符号列表，允许用 Emoji 作为视觉分隔\n"
        "- 不同周的点评语气要根据实际数据变化：进步了就明确说进步了，退步了就直说\n"
        "- 对于重复出现的问题（如心率总偏高）可以直接说'老问题又来了'，不要每次重新解释\n"
        "- 允许有情绪：'这周跑得漂亮'、'说实话这周浪费了两次训练机会'\n\n"

        "【内容逻辑（根据数据灵活取舍，不要每项都写）】\n"
        "1. 🎯 一句话定调：这周总体是加分还是减分，为什么（30字以内）\n"
        "2. 📊 最值得讨论的一件事：可以是亮点也可以是隐患，只选最重要的一件，展开说透\n"
        "   - 如果TSB < -15，重点说疲劳风险，其他可以略过\n"
        "   - 如果LSD Decouple > 8%，重点说有氧基础问题\n"
        "   - 如果本周有质量课(T跑/间歇)完成，重点评价执行质量\n"
        "   - 如果本周全是E跑，指出结构单一\n"
        "3. 🗓️ 下周执行指令（必须量化）：\n"
        "   ① 总跑量区间\n"
        "   ② 最重要的一次课（类型+距离+配速区间+心率上限），其他日子一句话带过\n"
        "   ③ 是否需要减量，原因一句话\n\n"

        "【输出要求】\n"
        "- 总字数250-320字\n"
        "- 第2点只选一个核心问题展开，不要面面俱到\n"
        "- 下周药方的配速和心率必须是具体数字，不接受模糊表达\n"
        "- 直接输出正文，无开头问候无结尾署名\n"
    )
    # 周报指标
    report_lines = []
    for k in ["Distance (km)", "Runs", "Avg Pace", "Weekly Load", "Fitness (CTL)", "Form (TSB)", "VDOT", "LSD Decouple", "Status"]:
        v = weekly_report_dict.get(k)
        if v is not None:
            report_lines.append(f"  {k}: {v}")
    report_blob = "\n".join(report_lines) if report_lines else "（无）"
    # 当周每次跑
    run_lines = []
    if hasattr(weekly_activities_df, "iterrows") and len(weekly_activities_df) > 0:
        for _, row in weekly_activities_df.iterrows():
            date = row.get("Date", "")
            name = row.get("Name", "")
            dist = row.get("Distance (km)", "")
            dur = row.get("Duration (min)", "")
            pace = row.get("Avg Pace", "")
            hr = row.get("Avg HR", "")
            run_lines.append(f"  {date} | {name} | {dist} km | {dur} min | 配速 {pace} | 平均心率 {hr}")
    runs_blob = "\n".join(run_lines) if run_lines else "（本周无跑步记录）"
    age = RUNNER_PROFILE.get("age")
    profile_blob = (
        f"【跑者画像】\n"
        f"  性别/年龄: {RUNNER_PROFILE.get('gender', '未知')}/{age or '未知'}岁\n"
        f"  目标赛事: {RUNNER_PROFILE.get('goal_race', '半马/全马')}\n"
        f"  目标成绩: {RUNNER_PROFILE.get('goal_time', '未设定')}\n"
        f"  历史伤病: {RUNNER_PROFILE.get('injury_history', '无')}\n\n"
    )
    user_parts = [profile_blob, f"本周周报指标：\n{report_blob}\n\n本周跑步记录：\n{runs_blob}"]
    if recent_weeks_reports and len(recent_weeks_reports) > 0:
        hist_lines = ["近期 6–8 周周报（供推断训练季阶段）："]
        for w in recent_weeks_reports[-8:]:
            ws = w.get("Week Start", w.get("Week End", ""))
            we = w.get("Week End", "")
            dist = w.get("Distance (km)", "")
            ctl = w.get("Fitness (CTL)", "")
            tsb = w.get("Form (TSB)", "")
            vdot = w.get("VDOT", "")
            hist_lines.append(f"  {ws}~{we} | 跑量 {dist} km | CTL {ctl} | TSB {tsb} | VDOT {vdot}")
        user_parts.insert(1, "\n".join(hist_lines) + "\n\n")
    user = "".join(user_parts)
    out = _call_llm(system, user, max_tokens=1050)
    if LLM_DELAY_SECONDS > 0:
        time.sleep(LLM_DELAY_SECONDS)
    return out


def get_activity_advice(activity_row, weekly_context=None, recent_activities: list = None) -> str:
    """
    根据单条跑步记录（及可选近期跑步、周报上下文）生成该次的教练点评。
    activity_row: Series 或 dict，含 Date, Name, Distance (km), Duration (min), Avg Pace, Avg HR, Cadence, Elevation 等
    recent_activities: 可选，近期 3–5 次跑步列表（dict 或 Series），按时间升序，最新在最后
    weekly_context: 可选 dict，含 Fitness (CTL), Form (TSB), VDOT 等
    跑者画像自动从环境变量 RUNNER_* 读取，可在 .env 中配置。
    返回纯文本建议；失败返回空串。
    """
    def _get(r, key, default=""):
        if hasattr(r, "get"):
            return r.get(key, default)
        try:
            return getattr(r, key, default)
        except Exception:
            return default

    def _fmt_run(r, is_target=False):
        date = _get(r, "Date")
        name = _get(r, "Name")
        dist = _get(r, "Distance (km)")
        dur = _get(r, "Duration (min)")
        pace = _get(r, "Avg Pace")
        hr = _get(r, "Avg HR")
        cad = _get(r, "Cadence (spm)")
        elev = _get(r, "Elevation Gain (m)")
        tag = " [本单]" if is_target else ""
        return f"  {date} | {name} | {dist} km | {dur} min | 配速 {pace} | 心率 {hr} | 步频 {cad} spm | 爬升 {elev} m{tag}"

    system = (
        "你是一位有15年带队经验的马拉松主教练，正在给熟悉的学员做单次训练复盘。\n"
        "你需要输出给 Google Sheet 的结构化点评，供不同列分别写入。\n\n"

        "【核心要求】\n"
        "- 必须严格输出 5 段，并且每段都用下面的标签开头，标签名一字不差：\n"
        "【总评】\n"
        "【配速】\n"
        "【心率】\n"
        "【步频与爬升】\n"
        "【下次训练课】\n"
        "- 每个标签只能出现一次，不能遗漏，不能合并。\n"
        "- 每个标签后的内容只写该维度，不要串到别的维度。\n"
        "- 不要输出除这 5 段之外的任何前言、结尾、列表符号或 Markdown。\n\n"

        "【各段写法】\n"
        "- 【总评】：30-70 字。判断这趟跑总体质量，直说好坏。\n"
        "- 【配速】：30-70 字。评价这次配速是否合理，并给下次同类训练的配速建议。\n"
        "- 【心率】：30-70 字。评价心率控制是否合理，并给下次心率上限或目标区间。\n"
        "- 【步频与爬升】：20-60 字。只谈步频、地形、爬升影响和动作经济性。\n"
        "- 【下次训练课】：40-90 字。必须给出下一次训练类型、距离或时长、配速范围、心率要求。\n\n"

        "【诊断原则】\n"
        "- 如果是恢复跑，就强调恢复质量，不要给高强度建议。\n"
        "- 如果是 LSD 但心率偏高，就明确指出跑成了混氧跑。\n"
        "- 如果近期训练背景有对比价值，可以引用一次，但不要复述整个历史。\n"
        "- 所有建议都要具体到数字，尤其是配速和心率。\n"
    )
    profile_blob = (
        f"【跑者画像】\n"
        f"  性别/年龄: {RUNNER_PROFILE.get('gender', '未知')}/{RUNNER_PROFILE.get('age') or '未知'}岁\n"
        f"  目标赛事: {RUNNER_PROFILE.get('goal_race', '半马/全马')}\n"
        f"  目标成绩: {RUNNER_PROFILE.get('goal_time', '未设定')}\n"
        f"  历史伤病: {RUNNER_PROFILE.get('injury_history', '无')}\n\n"
    )
    prompt_parts = []
    prompt_parts.append("本单跑步数据：\n")
    prompt_parts.append(_fmt_run(activity_row, is_target=True))
    if weekly_context:
        prompt_parts.append("\n当前周报参考: " + str({k: weekly_context.get(k) for k in ["Fitness (CTL)", "Form (TSB)", "VDOT"] if k in weekly_context}))
    user = profile_blob + "".join(prompt_parts)
    if recent_activities:
        recent_lines = []
        for r in recent_activities[-4:]:  # 最近4次
            r_dict = r.to_dict() if hasattr(r, "to_dict") else r
            recent_lines.append(
                f"  {r_dict.get('Date','')} | {r_dict.get('Distance (km)','')}km "
                f"| 配速{r_dict.get('Avg Pace','')} | 心率{r_dict.get('Avg HR','')}"
            )
        user += "\n\n最近训练背景（供参考，不要逐条点评）：\n" + "\n".join(recent_lines)
    out = _call_llm(system, user, max_tokens=750)
    if LLM_DELAY_SECONDS > 0:
        time.sleep(LLM_DELAY_SECONDS)
    return out
