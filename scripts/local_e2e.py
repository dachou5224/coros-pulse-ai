#!/usr/bin/env python3
"""
离线本地 E2E：
1. 用假 Strava 数据跑 src/main.py
2. 写入内存版 Google Sheets
3. 跑 src/analysis.py 生成 Weekly_Report + 周报点评
4. 跑 src/activity_advice.py 生成单次点评
5. 导出 CSV，并截图 show/app.py 与 show/static/index.html

默认不访问真实 Strava / Google Sheets / Gemini。
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from urllib.parse import urlencode


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import analysis  # type: ignore  # noqa: E402
import activity_advice  # type: ignore  # noqa: E402
import coach  # type: ignore  # noqa: E402
import main as sync_main  # type: ignore  # noqa: E402


FIXED_NOW = datetime(2026, 3, 31, 9, 0, 0)
SHEET_NAME = "Coros_Running_Data"


@dataclass
class FakeSummary:
    id: int
    type: str


@dataclass
class FakeSplit:
    split: int
    average_speed: float
    average_heartrate: int


class FakeActivity(SimpleNamespace):
    pass


def _seed_activities() -> list[FakeActivity]:
    def dt(s: str) -> datetime:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")

    raw = [
        dict(
            id=100001,
            name="恢复慢跑",
            start_date_local=dt("2026-03-10 06:30:00"),
            distance=8200.0,
            moving_time=49 * 60,
            average_speed=2.79,
            max_speed=3.30,
            average_heartrate=136,
            max_heartrate=148,
            suffer_score=28,
            average_watts=198,
            average_cadence=84,
            total_elevation_gain=35,
            kilojoules=420,
            average_temp=12,
            gear_id="shoe-a",
            gear=SimpleNamespace(name="Mach 6"),
            type="Run",
            splits_metric=[
                FakeSplit(1, 2.82, 132),
                FakeSplit(2, 2.80, 135),
                FakeSplit(3, 2.77, 137),
                FakeSplit(4, 2.75, 139),
            ],
        ),
        dict(
            id=100002,
            name="节奏跑",
            start_date_local=dt("2026-03-18 07:00:00"),
            distance=12000.0,
            moving_time=64 * 60,
            average_speed=3.12,
            max_speed=4.35,
            average_heartrate=152,
            max_heartrate=168,
            suffer_score=56,
            average_watts=236,
            average_cadence=87,
            total_elevation_gain=60,
            kilojoules=670,
            average_temp=15,
            gear_id="shoe-b",
            gear=SimpleNamespace(name="Adios Pro"),
            type="Run",
            splits_metric=[
                FakeSplit(1, 3.00, 145),
                FakeSplit(2, 3.05, 149),
                FakeSplit(3, 3.12, 153),
                FakeSplit(4, 3.18, 156),
                FakeSplit(5, 3.20, 159),
            ],
        ),
        dict(
            id=100003,
            name="E 配速晨跑",
            start_date_local=dt("2026-03-24 06:20:00"),
            distance=10000.0,
            moving_time=58 * 60,
            average_speed=2.87,
            max_speed=3.40,
            average_heartrate=140,
            max_heartrate=151,
            suffer_score=34,
            average_watts=205,
            average_cadence=85,
            total_elevation_gain=42,
            kilojoules=510,
            average_temp=16,
            gear_id="shoe-a",
            gear=SimpleNamespace(name="Mach 6"),
            type="Run",
            splits_metric=[
                FakeSplit(1, 2.90, 136),
                FakeSplit(2, 2.88, 139),
                FakeSplit(3, 2.86, 141),
                FakeSplit(4, 2.84, 143),
                FakeSplit(5, 2.82, 145),
            ],
        ),
        dict(
            id=100004,
            name="间歇课 6x800",
            start_date_local=dt("2026-03-26 19:10:00"),
            distance=9600.0,
            moving_time=50 * 60,
            average_speed=3.20,
            max_speed=4.85,
            average_heartrate=158,
            max_heartrate=176,
            suffer_score=71,
            average_watts=258,
            average_cadence=89,
            total_elevation_gain=55,
            kilojoules=600,
            average_temp=18,
            gear_id="shoe-b",
            gear=SimpleNamespace(name="Adios Pro"),
            type="Run",
            splits_metric=[
                FakeSplit(1, 3.10, 148),
                FakeSplit(2, 3.20, 154),
                FakeSplit(3, 3.28, 160),
                FakeSplit(4, 3.33, 166),
                FakeSplit(5, 3.38, 170),
                FakeSplit(6, 3.25, 164),
            ],
        ),
        dict(
            id=100005,
            name="周末 LSD",
            start_date_local=dt("2026-03-29 07:15:00"),
            distance=22000.0,
            moving_time=132 * 60,
            average_speed=2.78,
            max_speed=3.30,
            average_heartrate=146,
            max_heartrate=161,
            suffer_score=88,
            average_watts=214,
            average_cadence=84,
            total_elevation_gain=105,
            kilojoules=1260,
            average_temp=19,
            gear_id="shoe-a",
            gear=SimpleNamespace(name="Mach 6"),
            type="Run",
            splits_metric=[
                FakeSplit(1, 2.85, 140),
                FakeSplit(2, 2.84, 142),
                FakeSplit(3, 2.82, 143),
                FakeSplit(4, 2.80, 145),
                FakeSplit(5, 2.78, 146),
                FakeSplit(6, 2.76, 147),
                FakeSplit(7, 2.73, 149),
                FakeSplit(8, 2.70, 151),
            ],
        ),
    ]
    return [FakeActivity(**item) for item in raw]


class FakeStravaClient:
    def __init__(self, activities: list[FakeActivity]):
        self.activities = {int(a.id): a for a in activities}

    def get_activities(self, limit: int = 3000):
        items = sorted(
            self.activities.values(), key=lambda x: x.start_date_local, reverse=True
        )[:limit]
        for item in items:
            yield FakeSummary(id=int(item.id), type=str(item.type))

    def get_activity(self, activity_id: int):
        return self.activities[int(activity_id)]


def _to_sheet_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _a1_to_row_col(a1: str) -> tuple[int, int]:
    col_part = ""
    row_part = ""
    for ch in a1:
        if ch.isalpha():
            col_part += ch.upper()
        elif ch.isdigit():
            row_part += ch
    col = 0
    for ch in col_part:
        col = col * 26 + (ord(ch) - 64)
    return int(row_part), col


class FakeWorksheet:
    def __init__(self, title: str, rows: list[list[Any]] | None = None, log: list | None = None):
        self.title = title
        self._rows = [list(r) for r in (rows or [])]
        self._log = log if log is not None else []

    @property
    def row_count(self) -> int:
        return max(len(self._rows), 100)

    def _ensure_size(self, row: int, col: int) -> None:
        while len(self._rows) < row:
            width = len(self._rows[0]) if self._rows else max(col, 1)
            self._rows.append([""] * width)
        for idx in range(len(self._rows)):
            while len(self._rows[idx]) < col:
                self._rows[idx].append("")

    def get_all_records(self) -> list[dict[str, Any]]:
        if not self._rows:
            return []
        headers = [str(h) for h in self._rows[0]]
        out = []
        for row in self._rows[1:]:
            if not any(str(v).strip() for v in row):
                continue
            padded = row + [""] * (len(headers) - len(row))
            out.append({headers[i]: padded[i] for i in range(len(headers))})
        return out

    def get_all_values(self) -> list[list[str]]:
        return [[_to_sheet_value(v) for v in row] for row in self._rows]

    def row_values(self, row: int) -> list[str]:
        if 1 <= row <= len(self._rows):
            return [_to_sheet_value(v) for v in self._rows[row - 1]]
        return []

    def append_row(self, row: list[Any]) -> None:
        self._rows.append(list(row))
        self._log.append({"sheet": self.title, "op": "append_row", "size": len(row)})

    def append_rows(self, rows: list[list[Any]]) -> None:
        for row in rows:
            self._rows.append(list(row))
        self._log.append({"sheet": self.title, "op": "append_rows", "count": len(rows)})

    def update_cell(self, row: int, col: int, value: Any) -> None:
        self._ensure_size(row, col)
        self._rows[row - 1][col - 1] = value
        self._log.append({"sheet": self.title, "op": "update_cell", "row": row, "col": col})

    def batch_update(self, data: list[dict[str, Any]]) -> None:
        for item in data:
            row, col = _a1_to_row_col(item["range"])
            values = item.get("values") or [[""]]
            self.update_cell(row, col, values[0][0] if values and values[0] else "")
        self._log.append({"sheet": self.title, "op": "batch_update", "count": len(data)})

    def sort(self, sort_spec: tuple[int, str], range: str | None = None) -> None:  # noqa: A003
        if len(self._rows) <= 2:
            return
        col_idx = max(1, int(sort_spec[0])) - 1
        reverse = str(sort_spec[1]).lower().startswith("des")
        header = self._rows[0]
        body = self._rows[1:]

        def key(row: list[Any]):
            value = row[col_idx] if len(row) > col_idx else ""
            text = _to_sheet_value(value)
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(text, fmt)
                except ValueError:
                    continue
            return text

        self._rows = [header] + sorted(body, key=key, reverse=reverse)
        self._log.append({"sheet": self.title, "op": "sort", "col": col_idx + 1, "reverse": reverse})

    def export_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            for row in self.get_all_values():
                writer.writerow(row)


class WorksheetNotFound(Exception):
    pass


class FakeSpreadsheet:
    def __init__(self, title: str, sheets: dict[str, FakeWorksheet], log: list):
        self.title = title
        self._sheets = sheets
        self._log = log

    @property
    def sheet1(self) -> FakeWorksheet:
        return self._sheets["Activities"]

    def worksheet(self, name: str) -> FakeWorksheet:
        if name == "Activities":
            return self.sheet1
        if name not in self._sheets:
            raise WorksheetNotFound(name)
        return self._sheets[name]

    def add_worksheet(self, title: str, rows: int, cols: int) -> FakeWorksheet:
        ws = FakeWorksheet(title, rows=[], log=self._log)
        self._sheets[title] = ws
        self._log.append({"sheet": title, "op": "add_worksheet", "rows": rows, "cols": cols})
        return ws


class FakeGSpreadClient:
    def __init__(self, spreadsheet: FakeSpreadsheet):
        self.spreadsheet = spreadsheet

    def open(self, name: str) -> FakeSpreadsheet:
        if name != self.spreadsheet.title:
            raise ValueError(f"unknown spreadsheet {name}")
        return self.spreadsheet


def _initial_workbook(log: list) -> FakeSpreadsheet:
    activities_headers = [
        "Activity ID",
        "Date",
        "Name",
        "Distance (km)",
        "Duration (min)",
        "Avg Pace",
        "Max Pace",
        "Avg HR",
        "Max HR",
        "Suffer Score",
        "Avg Power (w)",
        "Cadence (spm)",
        "Elevation Gain (m)",
        "Calories (kcal)",
        "Temperature (C)",
        "Shoes",
        "Type",
        "Splits (JSON)",
    ]
    settings_rows = [
        ["Date", "Max HR", "Rest HR"],
        ["2026-01-01", "185", "55"],
        ["2026-03-01", "188", "54"],
    ]
    sheets = {
        "Activities": FakeWorksheet("Activities", rows=[activities_headers], log=log),
        "Settings": FakeWorksheet("Settings", rows=settings_rows, log=log),
    }
    return FakeSpreadsheet(SHEET_NAME, sheets, log)


def _fake_llm(system: str, user: str, max_tokens: int = 600) -> str:
    if "本单跑步数据" in user:
        return (
            "【总评】这次训练执行基本在线，强度没有失控，但末段心率已经开始往上飘。\n"
            "【配速】前半程配速稳定，后半程建议主动慢 10 到 15 秒每公里。\n"
            "【心率】把有氧跑心率继续压在 145 以下，质量课再允许上到 165 左右。\n"
            "【步频与爬升】步频保持住了，爬升对整体负荷有加成，不必额外补强度。\n"
            "【下次训练课】下一次同类课跑 50 到 60 分钟，配速 5'50\"-6'05\"，心率不超过 145。"
        )
    return (
        "【本周总评】这周训练完成度不错，量和强度都有，但长距离后段的有氧稳定性还差半步。\n"
        "【核心诊断】间歇课说明速度能力在线，真正需要盯的是 LSD 后半程心率漂移，说明你在疲劳下的经济性还不够稳。\n"
        "【下周药方】下周总量先放在 46 到 52 公里，保留一次节奏跑 8 公里，配速 5'05\"-5'15\"；周末 LSD 控制在 18 到 20 公里，心率上限 148。"
    )


def _write_summary(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_static_site(out_dir: Path) -> Path:
    static_dir = out_dir / "static"
    if static_dir.exists():
        shutil.rmtree(static_dir)
    shutil.copytree(REPO_ROOT / "show" / "static", static_dir)
    return static_dir


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, timeout_s: float = 30.0) -> None:
    import urllib.request

    deadline = time.time() + timeout_s
    last_error = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # nosec B310
                if resp.status < 500:
                    return
        except Exception as exc:  # pragma: no cover
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"等待服务超时: {url} ({last_error})")


def _start_static_server(root: Path, port: int):
    prev_cwd = Path.cwd()
    os.chdir(root)
    server = ThreadingHTTPServer(("127.0.0.1", port), SimpleHTTPRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, prev_cwd


def _run_streamlit(csv_path: str, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["WEEKLY_REPORT_CSV_URL"] = csv_path
    env["WEEKLY_REPORT_CSV_CACHE_TTL_SEC"] = "60"
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "show/app.py",
            "--server.headless",
            "true",
            "--server.port",
            str(port),
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _capture(url: str, path: Path, *, wait_ms: int = 2000) -> None:
    from playwright.sync_api import sync_playwright

    path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1800})
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(wait_ms)
        page.screenshot(path=str(path), full_page=True)
        browser.close()


def run_e2e(out_dir: Path, *, with_ui: bool = True) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    workbook_log: list[dict[str, Any]] = []
    spreadsheet = _initial_workbook(workbook_log)
    fake_client = FakeGSpreadClient(spreadsheet)
    fake_strava = FakeStravaClient(_seed_activities())

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_NOW if tz is None else tz.fromutc(FIXED_NOW.replace(tzinfo=tz))

    summary: dict[str, Any] = {
        "out_dir": str(out_dir),
        "fixed_now": FIXED_NOW.isoformat(),
        "ui": {},
    }

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(sync_main, "get_strava_client", return_value=fake_strava))
        stack.enter_context(patch.object(sync_main, "get_google_sheet", return_value=spreadsheet.sheet1))
        stack.enter_context(patch.object(analysis, "get_client", return_value=fake_client))
        stack.enter_context(patch.object(activity_advice, "get_client", return_value=fake_client))
        stack.enter_context(patch.object(activity_advice, "_ADVICE_LOOP_DELAY", 0.0))
        stack.enter_context(patch.object(coach, "_call_llm", side_effect=_fake_llm))
        stack.enter_context(patch.object(analysis, "datetime", FixedDateTime))

        # 让 analysis / activity_advice 捕获到本地 WorksheetNotFound
        fake_gspread = SimpleNamespace(WorksheetNotFound=WorksheetNotFound)
        stack.enter_context(patch.object(analysis, "gspread", fake_gspread))
        stack.enter_context(patch.object(activity_advice, "gspread", fake_gspread))

        os.environ.setdefault("ACTIVITY_ADVICE_LIMIT", "10")

        sync_main.main()
        analysis.main()
        activity_advice.main()

    activities_ws = spreadsheet.sheet1
    weekly_ws = spreadsheet.worksheet("Weekly_Report")

    activities_csv = out_dir / "activities.csv"
    weekly_csv = out_dir / "weekly_report.csv"
    activities_ws.export_csv(activities_csv)
    weekly_ws.export_csv(weekly_csv)
    _write_summary(out_dir / "sheet_ops.json", {"ops": workbook_log})
    commands_txt = out_dir / "run_ui_commands.txt"
    commands_txt.write_text(
        "\n".join(
            [
                "# Streamlit 周报 UI（读取本地导出的 Weekly_Report CSV）",
                f"WEEKLY_REPORT_CSV_URL='{weekly_csv}' ./.venv/bin/python -m streamlit run show/app.py",
                "",
                "# 静态页（展示周报 + 单次点评），需在产物目录启动本地静态服务",
                f"cd '{out_dir}' && python3 -m http.server 8000",
                "",
                "# 打开后访问：",
                "http://127.0.0.1:8000/static/index.html?data=http://127.0.0.1:8000/weekly_report.csv&activity_advice=http://127.0.0.1:8000/activities.csv",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    activity_rows = activities_ws.get_all_records()
    weekly_rows = weekly_ws.get_all_records()
    advice_count = sum(1 for row in activity_rows if str(row.get("总评", "")).strip())
    summary.update(
        {
            "activities_rows": len(activity_rows),
            "weekly_rows": len(weekly_rows),
            "activity_advice_rows": advice_count,
            "weekly_latest": weekly_rows[-1] if weekly_rows else {},
            "run_ui_commands": str(commands_txt),
        }
    )

    if with_ui:
        try:
            _copy_static_site(out_dir)
            http_port = _find_free_port()
            streamlit_port = _find_free_port()
            http_server, _http_thread, prev_cwd = _start_static_server(out_dir, http_port)
            streamlit_proc = _run_streamlit(str(weekly_csv), streamlit_port)
            try:
                _wait_http(f"http://127.0.0.1:{http_port}/weekly_report.csv")
                _wait_http(f"http://127.0.0.1:{streamlit_port}")

                streamlit_url = f"http://127.0.0.1:{streamlit_port}"
                static_query = urlencode(
                    {
                        "data": f"http://127.0.0.1:{http_port}/weekly_report.csv",
                        "activity_advice": f"http://127.0.0.1:{http_port}/activities.csv",
                    }
                )
                static_url = f"http://127.0.0.1:{http_port}/static/index.html?{static_query}"

                _capture(streamlit_url, out_dir / "screenshots" / "show_streamlit.png", wait_ms=2500)
                _capture(static_url, out_dir / "screenshots" / "show_static.png", wait_ms=1500)
                summary["ui"] = {
                    "status": "ok",
                    "streamlit_url": streamlit_url,
                    "static_url": static_url,
                    "screenshots": [
                        "screenshots/show_streamlit.png",
                        "screenshots/show_static.png",
                    ],
                }
            finally:
                streamlit_proc.terminate()
                with contextlib.suppress(Exception):
                    streamlit_proc.wait(timeout=5)
                with contextlib.suppress(Exception):
                    http_server.shutdown()
                with contextlib.suppress(Exception):
                    http_server.server_close()
                with contextlib.suppress(Exception):
                    os.chdir(prev_cwd)
        except Exception as e:
            summary["ui"] = {
                "status": "error",
                "error": str(e),
                "hint": f"see {commands_txt} and run the UI checks on your local machine",
            }

    _write_summary(out_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local offline E2E for coros-pulse-ai")
    parser.add_argument(
        "--out-dir",
        default=str(REPO_ROOT / "archive" / "output" / "local_e2e"),
        help="artifact output directory",
    )
    parser.add_argument(
        "--skip-ui",
        action="store_true",
        help="skip Streamlit/static UI screenshot phase",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    summary = run_e2e(out_dir, with_ui=not args.skip_ui)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
