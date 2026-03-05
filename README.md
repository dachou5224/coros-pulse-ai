# coros-pulse-ai

基于 Strava 与 Google Sheets 的跑步数据同步与周报分析流水线：拉取活动、计算 TRIMP/CTL/TSB/VDOT 等指标并写入周报表，另提供 Streamlit 看板读取同一张表做展示。

---

## 功能概览

- **Strava 同步**（`src/main.py`）：定时拉取 Strava 活动，写入 Google Sheet「Coros_Running_Data」的 Activities 表，含每公里 splits（配速、心率）的 JSON。
- **周报分析**（`src/analysis.py`）：按周汇总跑量、计算 TRIMP/CTL/ATL/TSB、VDOT、LSD 解耦率等，写入同一 Sheet 的 **Weekly_Report** 表。
- **历史回填**（`src/history_backfill.py`）：手动一次性按历史数据生成完整周报（用于首次建表或补全）。
- **Streamlit 看板**（`src/app.py`）：从同一 Sheet 的 Weekly_Report 读数据（gspread + Secrets），展示核心看板、历史与指标说明。
- **周期训练周报展示**（`show/app.py`）：从 Weekly_Report 的 CSV URL 读数据（无需 GCP 凭证），展示 PMC、TSB、VDOT、LSD 解耦等；可选环境变量 `WEEKLY_REPORT_CSV_URL` 覆盖默认链接。

---

## 仓库结构

```
coros-pulse-ai/
├── src/
│   ├── main.py           # Strava → Google Sheet 同步
│   ├── analysis.py      # 周报计算 → Weekly_Report
│   ├── history_backfill.py  # 历史周报回填
│   └── app.py           # Streamlit 看板（gspread + Secrets）
├── show/                 # 原 coros-data-show：周期训练周报展示（CSV 只读）
│   ├── app.py            # Streamlit 入口
│   ├── static/           # 静态 HTML 替代（index.html=周期训练周报，含指标说明）
│   ├── assets/styles.css
│   └── content/
├── .github/workflows/
│   ├── sync.yml         # 定时同步 Strava
│   ├── weekly_report.yml   # 每周一生成周报
│   └── backfill_history.yml # 手动回填
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 环境与密钥（敏感信息勿提交）

所有敏感信息均通过环境变量或 Secrets 注入，**不要**在代码或仓库中写入 token、JSON 密钥。

### 本地 / 脚本运行

| 变量名 | 用途 |
|--------|------|
| `STRAVA_CLIENT_ID` | Strava 应用 Client ID |
| `STRAVA_CLIENT_SECRET` | Strava 应用 Client Secret |
| `STRAVA_REFRESH_TOKEN` | Strava 刷新 Token |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | 谷歌服务账号 JSON 整段字符串（用于 gspread 写 Sheet） |

- 同步与周报脚本：上述变量需在运行环境中设置（如 `.env` + `python-dotenv`，且 `.env` 已加入 `.gitignore`）。
- Streamlit 看板（`src/app.py`）使用 **Streamlit Secrets**：在 `.streamlit/secrets.toml` 中配置 `gcp_service_account`（或云平台提供的 Secrets），用于读 Sheet。**勿将 `secrets.toml` 提交到仓库。**
- 周期训练周报展示（`show/app.py`）**可选**环境变量：`WEEKLY_REPORT_CSV_URL`（Weekly Report 表 CSV 导出链接，不设则使用代码内默认公开链接）。

### GitHub Actions

在仓库 **Settings → Secrets and variables → Actions** 中配置：

| Secret 名称 | 用途 |
|-------------|------|
| `STRAVA_CLIENT_ID` | sync.yml 同步 Strava |
| `STRAVA_CLIENT_SECRET` | sync.yml |
| `STRAVA_REFRESH_TOKEN` | sync.yml |
| `GOOGLE_JSON_KEY` | sync.yml / weekly_report.yml / backfill_history.yml 写 Sheet |

---

## 运行方式

### 依赖

```bash
pip install -r requirements.txt
```

### 同步 Strava 活动

```bash
# 需设置 STRAVA_* 与 GOOGLE_APPLICATION_CREDENTIALS_JSON
python src/main.py
```

### 生成周报（当周/上周）

```bash
# 需设置 GOOGLE_APPLICATION_CREDENTIALS_JSON
python src/analysis.py
```

### 历史周报回填（一次性）

```bash
# 需设置 GOOGLE_APPLICATION_CREDENTIALS_JSON
python src/history_backfill.py
```

### Streamlit 看板（pulse）

```bash
# 需在 Streamlit 中配置 gcp_service_account（如 .streamlit/secrets.toml）
streamlit run src/app.py
```

### 周期训练周报展示（show）

```bash
# 在仓库根目录执行；数据来自 Weekly Report 的 CSV，可选环境变量 WEEKLY_REPORT_CSV_URL
streamlit run show/app.py
```

### 静态 HTML 展示（轻量替代，无需 Python）

`show/static/` 下提供纯前端版本，可直接用浏览器打开或部署到任意静态托管（GitHub Pages、Netlify、Vercel 等），无需 Streamlit 或 Docker。

| 入口 | 说明 |
|------|------|
| `show/static/index.html` | 周期训练周报（近四周 PMC/TSB/VDOT/LSD 图表、KPI、指标说明） |

- **数据源**：默认使用与 `show/app.py` 相同的公开 CSV URL；若遇 CORS 限制，可通过 URL 参数 `?data=同源 JSON 地址` 或部署时提供同源数据。
- **本地预览**：用浏览器直接打开 `show/static/index.html`；或 `cd show/static && python -m http.server 8080` 后访问 `http://localhost:8080`。
- **部署示例**：可将 `show/static/` 下的文件同步到 VPS（如 `/var/www/run`），配合 Nginx 配置 `server_name run.nice-ai.dev; root /var/www/run;` 作为独立子站使用。

---

## 自动化（GitHub Actions）

- **sync.yml**：按 cron 定时（默认每 15 分钟）运行 `main.py`，将新活动写入 Sheet。
- **weekly_report.yml**：每周一 UTC 0:00 运行 `analysis.py`，生成当周周报。
- **backfill_history.yml**：仅支持手动触发（workflow_dispatch），运行 `history_backfill.py` 做历史回填。

确保仓库已配置上述 4 个 Actions Secrets，否则工作流会因缺少凭证而失败。

---

## 与 coros-data-show 的关系

**原 coros-data-show 已合并至本仓库的 `show/` 目录**。若曾单独克隆 coros-data-show，可改为使用本仓的 `show/` 入口：`streamlit run show/app.py`。  
show 为**只读展示**：通过 Weekly_Report 的 CSV URL（或环境变量 `WEEKLY_REPORT_CSV_URL`）读数据，无需 GCP 凭证；本仓 `src/` 负责**写** Sheet（同步 + 周报）。

---

## 数据与指标说明

- **Sheet 表名**：`Coros_Running_Data`（可在 `main.py` 中修改 `SHEET_NAME`）。
- **周报表**：`Weekly_Report`，含 Week Start/End、Distance、Weekly Load、Fitness (CTL)、Form (TSB)、VDOT、LSD Decouple、Status 等列。
- **指标含义**：见 `src/app.py` 内「指标百科」Tab，或本仓 `show/` 页面展示的周报结构。

每公里 splits 数据来自 Strava 活动详情的 `splits_metric`，已写入 Activities 表对应列的 JSON；若需更细粒度，可后续对接 Strava Streams API 按 1 km 分桶。
