"""
卡片渲染：优先用 PIL 在固定版式上只填数据与教练点评（借鉴 year-sport 做法，无需每次起浏览器）；
无 Pillow 时回退到 HTML + playwright / html2image。
"""
import os
import subprocess
import sys
import warnings

# 抑制 urllib3 等依赖的 OpenSSL 警告，避免污染终端
warnings.filterwarnings("ignore", message=".*OpenSSL.*", category=UserWarning)
warnings.filterwarnings("ignore", module="urllib3")
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

try:
    from html2image import Html2Image
    _HTML2IMAGE_AVAILABLE = True
except ImportError:
    _HTML2IMAGE_AVAILABLE = False

# 项目根目录（本文件所在目录）
ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "card_template"
# 字体：优先本仓库 assets，其次借用 year-sport 的 assets（同层级目录）
_ASSETS_DIRS = [ROOT / "assets", ROOT.parent / "year-sport" / "assets"]
# 中文/CJK 字体候选（Inter 无中文会导致文案不显示）
_CJK_FONT_PATHS = [
    *(base / "NotoSansSC-Regular.otf" for base in _ASSETS_DIRS),
    *(base / "NotoSansSC-Regular.ttf" for base in _ASSETS_DIRS),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
]

_CHROMIUM_ARGS = [
    "--log-level=3", "--disable-logging", "--disable-dev-shm-usage",
    "--disable-gpu", "--disable-software-rasterizer",
    "--disable-background-networking", "--no-first-run", "--no-default-browser-check",
]

# 在 Cursor/Electron 下用 Playwright 启动 Chrome 可能触发 macOS 崩溃（HIServices）。
# 设置 PREFER_HTML2IMAGE=1 可跳过 Playwright，仅用 html2image 渲染，避免弹窗。
_PREFER_HTML2IMAGE = os.environ.get("PREFER_HTML2IMAGE", "").strip().lower() in ("1", "true", "yes")

# 固定手机竖屏尺寸（与 coach.py 中字数上限一致，用于固定画布与区块高度）
# coach: 单次点评 250 字以内，周报 350 字以内；下次目标/下周重点为 1–2 句摘要
CARD_W, CARD_H = 1080, 1920
ACTIVITY_ADVICE_MAX_CHARS = 250
ACTIVITY_NEXT_GOAL_MAX_LINES = 3
WEEKLY_ADVICE_MAX_CHARS = 350
WEEKLY_FOCUS_MAX_LINES = 4


def _load_font(name: str, size: int):
    """从 assets 目录加载字体，支持本仓库或 year-sport 的 assets。"""
    for base in _ASSETS_DIRS:
        path = base / name
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size)
            except Exception:
                pass
    return ImageFont.load_default()


def _load_font_cjk(size: int):
    """加载支持中文的字体，用于卡片内所有文案（Inter 无中文字形会显示为空白）。"""
    for path in _CJK_FONT_PATHS:
        if not path.exists():
            continue
        try:
            if path.suffix.lower() == ".ttc":
                return ImageFont.truetype(str(path), size, index=0)
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap_text(draw, text: str, font, max_width: int):
    """按像素宽度换行，返回行列表。"""
    lines = []
    for para in (text or "").replace("\r\n", "\n").split("\n"):
        para = para.strip()
        if not para:
            lines.append("")
            continue
        while para:
            # 逐字试探，直到超出 max_width
            for i in range(len(para), 0, -1):
                chunk = para[:i]
                bbox = draw.textbbox((0, 0), chunk, font=font)
                if bbox[2] - bbox[0] <= max_width:
                    lines.append(chunk)
                    para = para[i:].lstrip()
                    break
            else:
                # 单字也超宽则强制一字一行
                lines.append(para[0])
                para = para[1:].lstrip()
    return lines if lines else [""]


def _render_activity_card_pil(activity_row: dict, advice_text: str, next_goal: str,
                               output_path: str, brand_tag: str) -> str:
    """单次跑步卡：固定 1080×1920 手机竖屏，区块与字号按 coach 上限（250 字）适配。"""
    W, H = CARD_W, CARD_H
    bg = (26, 30, 46)
    gold = (255, 107, 53)
    white = (224, 224, 224)
    grey = (136, 136, 136)

    # 字号与行高放大，使文案区约占画布 2/3–3/4，便于阅读（250 字 / 8 行、下次目标 3 行）
    font_title = _load_font_cjk(38)
    font_small = _load_font_cjk(15)
    font_sub = _load_font_cjk(22)
    font_advice = _load_font_cjk(36)
    line_h_advice = 88
    max_advice_lines = 8
    next_box_title_h = 32
    next_box_line_h = 64

    tmp = Image.new("RGB", (W, 1), bg)
    tmp_draw = ImageDraw.Draw(tmp)
    advice_plain = (advice_text or "").replace("<br>", "\n").strip()
    advice_lines = _wrap_text(tmp_draw, advice_plain, font_advice, W - 80)[:max_advice_lines]
    next_lines = _wrap_text(tmp_draw, next_goal or "", font_advice, W - 120)[:ACTIVITY_NEXT_GOAL_MAX_LINES]

    y_div = 310
    y_advice_start = y_div + 52
    advice_block_h = max_advice_lines * line_h_advice
    y_goal_start = y_advice_start + advice_block_h + 28
    next_box_h = next_box_title_h + ACTIVITY_NEXT_GOAL_MAX_LINES * next_box_line_h

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    def get(k, *alt):
        for key in (k,) + alt:
            v = activity_row.get(key) if isinstance(activity_row, dict) else None
            if v is not None and str(v).strip():
                return str(v).strip()
        return "-"

    draw.rectangle([0, 0, W, 6], fill=gold)
    draw.text((40, 48), "AI COACH", font=font_sub, fill=grey)
    draw.text((W - 40, 48), get("Date", "date"), font=font_sub, fill=grey, anchor="ra")
    y_metrics = 116
    metrics = [
        (get("Distance (km)", "distance", "Distance"), "距离 (km)"),
        (get("Duration (min)", "duration", "Duration"), "时长 (min)"),
        (get("Avg Pace", "pace", "Pace"), "配速"),
        (get("Avg HR", "avg_hr", "Avg HR"), "心率 (bpm)"),
        (get("Cadence (spm)", "cadence", "Cadence"), "步频 (spm)"),
    ]
    n = len(metrics)
    cell_w = (W - 80) // n
    for i, (val, label) in enumerate(metrics):
        x = 40 + i * cell_w + cell_w // 2
        draw.text((x, y_metrics), val, font=font_title, fill=gold, anchor="mt")
        draw.text((x, y_metrics + 40), label, font=font_small, fill=grey, anchor="mt")
    elev = get("Elevation Gain (m)", "elevation", "Elevation")
    if elev != "-" and str(elev).replace(".", "").replace("-", "").isdigit():
        elev = f"爬升 {elev} m"
    draw.text((W // 2, y_metrics + 82), elev, font=font_sub, fill=grey, anchor="mt")
    training_type = get("Training Type", "training_type")
    if training_type == "-":
        training_type = "LSD"
    goal_race = os.getenv("RUNNER_GOAL_RACE", "全马备战").strip() or "全马备战"
    draw.text((40, y_metrics + 122), f"  {training_type}  ·  {goal_race}  ", font=font_sub, fill=gold)
    draw.line([(40, y_div), (W - 40, y_div)], fill=(255, 255, 255, 80), width=1)
    draw.text((W // 2, y_div + 22), "教练点评", font=font_sub, fill=grey, anchor="mt")
    y_advice = y_advice_start
    for line in advice_lines:
        draw.text((40, y_advice), line, font=font_advice, fill=white)
        y_advice += line_h_advice
    y_goal = y_goal_start
    draw.rectangle([40, y_goal, W - 40, y_goal + next_box_h], outline=gold, width=2)
    draw.text((56, y_goal + 8), "下次目标", font=font_sub, fill=gold)
    for i, line in enumerate(next_lines):
        draw.text((56, y_goal + next_box_title_h + i * next_box_line_h), line, font=font_advice, fill=white)
    draw.text((W // 2, H - 48), brand_tag or "#AI跑步教练 #马拉松备战", font=font_sub, fill=grey, anchor="mt")
    os.makedirs(os.path.dirname(output_path) or "output", exist_ok=True)
    img.save(output_path)
    return str(Path(output_path).resolve())


def _render_weekly_card_pil(weekly_report_dict: dict, advice_text: str, week_label: str,
                             next_week_focus: str, output_path: str, brand_tag: str) -> str:
    """周报卡：固定 1080×1920 手机竖屏，区块与字号按 coach 上限（350 字）适配。"""
    W, H = CARD_W, CARD_H
    bg = (255, 255, 255)
    dark = (26, 26, 46)
    gold = (255, 107, 53)
    grey = (102, 102, 102)
    grey_light = (153, 153, 153)

    # 字号与行高放大，使文案区约占画布 2/3–3/4（350 字 / 10 行、下周重点 4 行）
    font_title = _load_font_cjk(44)
    font_metric = _load_font_cjk(30)
    font_small = _load_font_cjk(15)
    font_section = _load_font_cjk(22)
    font_advice = _load_font_cjk(32)
    max_advice_lines = 12
    line_h_advice = 70
    focus_box_title_h = 32
    focus_box_line_h = 56

    tmp = Image.new("RGB", (W, 1), bg)
    tmp_draw = ImageDraw.Draw(tmp)
    advice_plain = (advice_text or "").replace("<br>", "\n").strip()
    advice_lines = _wrap_text(tmp_draw, advice_plain, font_advice, W - 112)[:max_advice_lines]
    focus_lines = _wrap_text(tmp_draw, next_week_focus or "", font_advice, W - 140)[:WEEKLY_FOCUS_MAX_LINES]

    y_bar = 112
    bar_h = 92
    y_sec = y_bar + bar_h + 78
    y_advice_start = y_sec + 50
    advice_block_h = max_advice_lines * line_h_advice
    y_focus_start = y_advice_start + advice_block_h + 28
    focus_box_h = focus_box_title_h + WEEKLY_FOCUS_MAX_LINES * focus_box_line_h

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    def get(k, *alt):
        d = weekly_report_dict if isinstance(weekly_report_dict, dict) else {}
        for key in (k,) + alt:
            v = d.get(key)
            if v is not None and str(v).strip():
                return str(v).strip()
        return "-"

    draw.rectangle([0, 0, 6, H], fill=gold)
    draw.text((56, 44), week_label or "周训练报告", font=font_title, fill=dark)
    draw.rectangle([56, y_bar, W - 56, y_bar + bar_h], fill=dark)
    metrics = [
        (get("Distance (km)", "total_km", "Distance"), "总跑量 (km)"),
        (get("Runs", "runs"), "出勤次数"),
        (get("Fitness (CTL)", "ctl", "CTL"), "CTL"),
        (get("Form (TSB)", "tsb", "TSB"), "TSB"),
        (get("VDOT", "vdot"), "VDOT"),
    ]
    n = len(metrics)
    cell_w = (W - 112) // n
    for i, (val, label) in enumerate(metrics):
        x = 56 + i * cell_w + cell_w // 2
        draw.text((x, y_bar + 24), val, font=font_metric, fill=gold, anchor="mt")
        draw.text((x, y_bar + 56), label, font=font_small, fill=(255, 255, 255, 200), anchor="mt")
    status = get("Status", "status")
    if status == "-":
        status = "训练中"
    draw.text((56, y_bar + bar_h + 26), f"  {status}  ", font=font_section, fill=gold)
    draw.line([(56, y_sec), (W - 56, y_sec)], fill=(238, 238, 238))
    draw.text((56, y_sec + 20), "本周诊断", font=font_section, fill=grey)
    y_advice = y_advice_start
    for line in advice_lines:
        draw.text((56, y_advice), line, font=font_advice, fill=(68, 68, 68))
        y_advice += line_h_advice
    y_focus = y_focus_start
    draw.rectangle([56, y_focus, W - 56, y_focus + focus_box_h], outline=gold, width=2)
    draw.text((72, y_focus + 10), "下周重点", font=font_section, fill=gold)
    for i, line in enumerate(focus_lines):
        draw.text((72, y_focus + focus_box_title_h + i * focus_box_line_h), line, font=font_advice, fill=(68, 68, 68))
    draw.text((W // 2, H - 48), brand_tag or "#AI跑步教练 #马拉松备战", font=font_section, fill=grey_light, anchor="mt")
    os.makedirs(os.path.dirname(output_path) or "output", exist_ok=True)
    img.save(output_path)
    return str(Path(output_path).resolve())


def _render_html_to_png(html_content: str, output_path: str, width: int = 1080):
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else "output", exist_ok=True)
    use_playwright = _PLAYWRIGHT_AVAILABLE and not _PREFER_HTML2IMAGE
    if use_playwright:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.set_content(html_content, wait_until="networkidle")
            height = page.evaluate("document.documentElement.scrollHeight")
            page.set_viewport_size({"width": width, "height": height})
            page.screenshot(path=output_path, full_page=True)
            browser.close()
    elif _HTML2IMAGE_AVAILABLE:
        hti = Html2Image(output_path=os.path.dirname(output_path) or "output")
        filename = os.path.basename(output_path)
        height = 1920 if "weekly" in output_path else 1400
        hti.screenshot(html_str=html_content, save_as=filename, size=(width, height))
    else:
        raise RuntimeError("需要安装 playwright 或 html2image：pip install playwright html2image && playwright install chromium")


def _safe(value, default: str = "-") -> str:
    """缺失或空时返回兜底值，否则转 str。"""
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return default
    return str(value).strip()


def _replace_placeholders(html: str, replacements: dict) -> str:
    """用 replace 逐一替换 {{变量名}}，未提供的键用 '-' 兜底。"""
    for key, val in replacements.items():
        html = html.replace("{{" + key + "}}", _safe(val))
    return html


def render_activity_card(
    activity_row: dict,
    advice_text: str,
    output_path: str = "output/activity_card.png",
    brand_tag: str = "#AI跑步教练 #马拉松备战",
) -> str:
    """
    渲染单次跑步点评卡。优先用 PIL 在固定版式上只填数据与点评（无需浏览器）；
    无 Pillow 时回退到 HTML + playwright / html2image。
    """
    advice_plain = (advice_text or "").strip()
    sentences = [s.strip() for s in advice_plain.split("。") if s.strip()]
    if len(sentences) >= 2:
        next_goal = sentences[-2] + "。"
    else:
        next_goal = advice_plain[-40:] if len(advice_plain) > 40 else (advice_plain or "暂无")

    if _PIL_AVAILABLE:
        out_path = str(Path(output_path).resolve())
        return _render_activity_card_pil(
            activity_row, advice_plain, next_goal, out_path, _safe(brand_tag)
        )

    # 回退：HTML 模板 + 浏览器/html2image
    template_path = TEMPLATE_DIR / "activity_card.html"
    html = template_path.read_text(encoding="utf-8")

    def get(key: str, *alt_keys: str) -> str:
        for k in (key,) + alt_keys:
            v = activity_row.get(k) if isinstance(activity_row, dict) else None
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        return "-"

    advice_html = advice_plain.replace("\n", "<br>")
    replacements = {
        "date": get("Date", "date"),
        "distance": get("Distance (km)", "distance", "Distance"),
        "duration": get("Duration (min)", "duration", "Duration"),
        "pace": get("Avg Pace", "pace", "Pace"),
        "avg_hr": get("Avg HR", "avg_hr", "Avg HR"),
        "cadence": get("Cadence (spm)", "cadence", "Cadence"),
        "elevation": get("Elevation Gain (m)", "elevation", "Elevation"),
        "training_type": get("Training Type", "training_type") if get("Training Type", "training_type") != "-" else "LSD",
        "goal_race": os.getenv("RUNNER_GOAL_RACE", "全马备战").strip() or "全马备战",
        "next_goal": next_goal.replace("\n", " "),
        "advice_text": advice_html,
        "brand_tag": _safe(brand_tag),
    }
    # 若 elevation 有值，格式化为 "爬升 X m"，否则兜底 "-"
    elev_raw = get("Elevation Gain (m)", "elevation", "Elevation")
    if elev_raw != "-" and str(elev_raw).replace(".", "").replace("-", "").isdigit():
        replacements["elevation"] = f"爬升 {elev_raw} m"
    else:
        replacements["elevation"] = elev_raw

    html = _replace_placeholders(html, replacements)

    out_path = str(Path(output_path).resolve())
    _render_html_to_png(html, out_path)
    return out_path


def render_weekly_card(
    weekly_report_dict: dict,
    advice_text: str,
    week_label: str = "",
    output_path: str = "output/weekly_card.png",
    brand_tag: str = "#AI跑步教练 #马拉松备战",
) -> str:
    """
    渲染周报点评卡。优先用 PIL 在固定版式上只填数据与点评（无需浏览器）；
    无 Pillow 时回退到 HTML + playwright / html2image。
    """
    def get(key: str, *alt_keys: str) -> str:
        d = weekly_report_dict if isinstance(weekly_report_dict, dict) else {}
        for k in (key,) + alt_keys:
            v = d.get(k)
            if v is not None and str(v).strip() != "":
                return str(v).strip()
        return "-"

    if not week_label or week_label.strip() == "":
        start_, end_ = get("Week Start", "week_start"), get("Week End", "week_end")
        week_label = f"第 {start_} ~ {end_} 周训练报告" if (start_ != "-" and end_ != "-") else "周训练报告"

    advice_plain = (advice_text or "").strip()
    sentences = [s.strip() for s in advice_plain.split("。") if s.strip()]
    # 下周重点：取开头的总结句，避免与「下周药方」里的 3、4 条重复
    def _is_numbered(s):
        s = s.strip()
        return len(s) > 2 and s[0] in "1234" and s[1] in ".．。"
    if sentences:
        summary = []
        for s in sentences:
            if _is_numbered(s):
                break
            summary.append(s)
        next_week_focus = "。".join(summary[:2]) if summary else sentences[0]
        if next_week_focus and not next_week_focus.endswith("。"):
            next_week_focus += "。"
    else:
        next_week_focus = advice_plain or "暂无"

    if _PIL_AVAILABLE:
        out_path = str(Path(output_path).resolve())
        return _render_weekly_card_pil(
            weekly_report_dict, advice_plain, week_label, next_week_focus, out_path, _safe(brand_tag)
        )

    # 回退：HTML 模板
    template_path = TEMPLATE_DIR / "weekly_card.html"
    html = template_path.read_text(encoding="utf-8")
    advice_html = advice_plain.replace("\n", "<br>")
    replacements = {
        "week_label": _safe(week_label, "周训练报告"),
        "total_km": get("Distance (km)", "total_km", "Distance"),
        "runs": get("Runs", "runs"),
        "ctl": get("Fitness (CTL)", "ctl", "CTL"),
        "tsb": get("Form (TSB)", "tsb", "TSB"),
        "vdot": get("VDOT", "vdot"),
        "status": get("Status", "status") if get("Status", "status") != "-" else "训练中",
        "advice_text": advice_html,
        "next_week_focus": next_week_focus.replace("\n", " "),
        "brand_tag": _safe(brand_tag),
    }

    html = _replace_placeholders(html, replacements)
    html = html.replace("{{status}}", str(weekly_report_dict.get("Status", "训练中") if isinstance(weekly_report_dict, dict) else "训练中"))

    out_path = str(Path(output_path).resolve())
    _render_html_to_png(html, out_path)
    return out_path


if __name__ == "__main__":
    # 用子进程重跑自身并关闭 stderr，使 Chromium 继承后不再往终端打 CVDisplayLink 等
    if os.environ.get("CARD_QUIET") != "1":
        result = subprocess.run(
            [sys.executable, __file__],
            env={**os.environ, "CARD_QUIET": "1"},
            stderr=subprocess.DEVNULL,
            stdout=sys.stdout,
        )
        sys.exit(result.returncode)
    # Mock 数据独立测试
    mock_activity = {
        "Date": "2026-03-08 07:08",
        "Name": "晨间跑步",
        "Distance (km)": "21.3",
        "Duration (min)": "128",
        "Avg Pace": "6:00",
        "Avg HR": "142",
        "Cadence (spm)": "172",
        "Elevation Gain (m)": "85",
    }
    mock_advice = "这是一次扎实的 LSD，心率控制良好，有氧效率在提升。下次可继续保持 6:00 左右配速，心率压在 136 以下。"

    path1 = render_activity_card(
        mock_activity,
        mock_advice,
        output_path="output/activity_card.png",
    )
    print("Activity card:", path1)

    mock_weekly = {
        "Week Start": "2026-02-23",
        "Week End": "2026-03-02",
        "Distance (km)": "45.15",
        "Runs": "6",
        "Fitness (CTL)": "71.4",
        "Form (TSB)": "-2.6",
        "VDOT": "42",
        "Status": "理想训练窗口",
    }
    mock_weekly_advice = "本周跑量 45km，出勤 6 次，CTL 71.4 体能扎实。TSB -2.6 处于理想窗口。下周建议 45-50km，安排 1 次 T 跑与 1 次 LSD。"

    path2 = render_weekly_card(
        mock_weekly,
        mock_weekly_advice,
        week_label="第 W23 周训练报告",
        output_path="output/weekly_card.png",
    )
    print("Weekly card:", path2)

# 依赖：PIL 优先（固定版式只填文字，无需浏览器）
#   pip install Pillow
# 字体：本仓库 assets/ 或同层级 year-sport/assets/ 下放 Inter-Bold.ttf、Inter-Regular.ttf 即可
# 无 Pillow 时回退到 HTML，需：pip install playwright html2image && playwright install chromium
