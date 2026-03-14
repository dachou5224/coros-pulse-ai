# coros-pulse-ai

基于 Strava 与 Google Sheets 的跑步数据同步与周报分析流水线：拉取活动、计算 TRIMP/CTL/TSB/VDOT 等指标并写入周报表，另提供 Streamlit 看板读取同一张表做展示。

---

## 功能概览

- **Strava 同步**（`src/main.py`）：定时拉取 Strava 活动，写入 Google Sheet「Coros_Running_Data」的 Activities 表，含每公里 splits（配速、心率）的 JSON。
- **周报分析**（`src/analysis.py`）：按周汇总跑量、计算 TRIMP/CTL/ATL/TSB、VDOT、LSD 解耦率等，写入同一 Sheet 的 **Weekly_Report** 表；可选调用 Gemini 生成本周教练点评与单次跑步点评（写入 Weekly_Report 的 Coach Advice 列与 **Activity_Advice** 表）。
- **历史回填**（`src/history_backfill.py`）：手动一次性按历史数据生成完整周报（用于首次建表或补全）。
- **Streamlit 看板**（`src/app.py`）：从同一 Sheet 的 Weekly_Report 读数据（gspread + Secrets），展示核心看板、历史与指标说明。
- **周期训练周报展示**（`show/app.py`）：从 Weekly_Report 的 CSV URL 读数据（无需 GCP 凭证），展示 PMC、TSB、VDOT、LSD 解耦等；可选环境变量 `WEEKLY_REPORT_CSV_URL` 覆盖默认链接。

---

## 仓库结构

```
coros-pulse-ai/
├── src/
│   ├── main.py              # Strava → Google Sheet 同步
│   ├── analysis.py          # 周报计算 → Weekly_Report + Coach Advice
│   ├── coach.py             # 教练点评（OpenAI 兼容调用 Gemini）
│   ├── activity_advice.py   # 单次跑步点评（独立脚本，写入 Activities 表）
│   ├── history_backfill.py  # 历史周报回填
│   ├── app.py               # Streamlit 看板 Pulse（gspread + Secrets）
│   └── test_coach.py        # 教练点评本地测试
├── show/                    # 周期训练周报展示（CSV 只读）
│   ├── app.py               # Streamlit 入口
│   ├── static/              # 静态 HTML（index.html，可部署至 VPS）
│   ├── assets/styles.css    # Streamlit 样式
│   └── content/
├── card_render.py           # 教练点评卡片图片生成（html2image）
├── card_template/           # 卡片 HTML 模板
├── assets/                  # 字体资源（Noto CJK 等，见 assets/README.md）
├── archive/                 # 历史归档（示例卡片等）
├── .github/workflows/
│   ├── sync.yml            # 每日同步 + 单次点评
│   ├── weekly_report.yml    # 每周周报
│   └── backfill_history.yml # 手动回填
├── requirements.txt
├── .env.example
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
- **教练点评**（`src/analysis.py` 调用 `src/coach.py`）：使用 OpenAI 兼容方式调用 Google Gemini，生成本周教练点评与单次跑步点评。可选环境变量（见 `.env.example`）：`API_KEY`（或 `GOOGLE_API_KEY` / `GEMINI_API_KEY`）、`BASE_URL`（如 `https://generativelanguage.googleapis.com/v1beta/openai`，勿带尾部斜线）、`COACH_MODEL` 或 `MODEL_NAME`（默认 `gemini-2.0-flash`）、`LLM_DELAY_SECONDS`。未配置时周报仍会写入，Coach Advice 列为「暂无」。

### GitHub Actions Secrets

在仓库 **Settings → Secrets and variables → Actions** 中新增以下 Secrets，否则 workflow 会因缺少凭证而失败：

| Secret 名称 | 用途 | 必需 |
|-------------|------|------|
| `STRAVA_CLIENT_ID` | sync.yml 同步 Strava 活动 | ✅ |
| `STRAVA_CLIENT_SECRET` | sync.yml | ✅ |
| `STRAVA_REFRESH_TOKEN` | sync.yml | ✅ |
| `GOOGLE_JSON_KEY` | sync.yml / weekly_report.yml / backfill_history.yml 写 Google Sheet（服务账号 JSON 整段） | ✅ |
| `API_KEY` | sync.yml 单次点评、weekly_report.yml 周报点评 调用 Gemini；与 `GEMINI_API_KEY` 二选一 | 教练点评必需 |
| `GEMINI_API_KEY` | 同上，Gemini API Key；与 `API_KEY` 二选一 | 教练点评必需 |

**说明**：`API_KEY` 与 `GEMINI_API_KEY` 任设其一即可；不设时周报仍会写入，Coach Advice 列为「暂无」，单次点评不生成。

本地开发时，参考 `.env.example` 配置 `.env`（已加入 `.gitignore`），包含：

- **Gemini**：`API_KEY`、`BASE_URL`、`COACH_MODEL`、`LLM_DELAY_SECONDS`
- **Google Sheet**：`GOOGLE_APPLICATION_CREDENTIALS_JSON`（或 `GOOGLE_APPLICATION_CREDENTIALS_FILE`）
- **跑者画像**（可选）：`RUNNER_GENDER`、`RUNNER_AGE`、`RUNNER_GOAL_RACE`、`RUNNER_GOAL_TIME`、`RUNNER_INJURY_HISTORY`
- **卡片生成**（可选）：`ENABLE_CARD_RENDER`、`CARD_BRAND_TAG`

GitHub Actions 中仅需配置上述 Secrets 表；跑者画像等可选变量在 CI 中不设则使用默认值。

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
| `show/static/index.html` | 周期训练周报（近四周 PMC/TSB/VDOT/LSD 图表、KPI、本周教练点评、单次跑步教练点评、指标说明） |

- **数据源**：默认使用与 `show/app.py` 相同的公开 CSV URL（周报含 Coach Advice 列时自动展示「本周教练点评」；也支持 本周总评/核心诊断/下周药方 三段合并展示）；若遇 CORS 限制，可通过 URL 参数 `?data=同源 JSON 地址` 或部署时提供同源数据。单次跑步教练点评需在 Google 表格中发布 **Activities** 表为 CSV，并通过 `?activity_advice=URL` 或 `window.ACTIVITY_ADVICE_URL` 传入，否则该区块显示「暂无单次跑步点评」。
- **本地预览**：用浏览器直接打开 `show/static/index.html`；或 `cd show/static && python -m http.server 8080` 后访问 `http://localhost:8080`。

#### VPS 部署（run.nice-ai.dev）

将 `show/static/` 部署到 VPS，配合 Nginx 作为独立子站。以下步骤不涉及任何私密信息，仅作流程说明。

**前置条件**：已有一台 VPS、域名已解析到该 VPS 的 IP。

**1. 创建目录并同步文件**

```bash
# 在 VPS 上创建目录（以 root 或 sudo 执行）
sudo mkdir -p /var/www/run
sudo chown $USER:$USER /var/www/run

# 本地执行：将 show/static/ 下所有文件同步到 VPS
rsync -avz --delete show/static/ user@YOUR_VPS_IP:/var/www/run/

# 或使用 scp
scp -r show/static/* user@YOUR_VPS_IP:/var/www/run/
```

**2. Nginx 配置**

在 VPS 上创建 `/etc/nginx/sites-available/run`（将 `run.nice-ai.dev` 替换为你的域名）：

```nginx
server {
    listen 80;
    server_name run.nice-ai.dev;
    root /var/www/run;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2)$ {
        expires 7d;
        add_header Cache-Control "public, immutable";
    }
}
```

启用并重载：

```bash
sudo ln -sf /etc/nginx/sites-available/run /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

**3. SSL（Let's Encrypt）**

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d run.nice-ai.dev
```

按提示完成验证后，Nginx 会自动添加 HTTPS 配置并续期。

**4. 自动部署（可选）**

若希望 push 到 main 后自动部署到 VPS，在仓库 **Settings → Secrets and variables → Actions** 中新增 `VPS_HOST`（VPS IP 或域名）、`VPS_USER`（SSH 用户名）、`VPS_SSH_KEY`（SSH 私钥完整内容）。新建 `.github/workflows/deploy.yml`：

```yaml
name: Deploy to VPS
on:
  push:
    branches: [main]
    paths: ['show/static/**']
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Deploy to VPS
        run: |
          mkdir -p ~/.ssh
          echo "${{ secrets.VPS_SSH_KEY }}" > ~/.ssh/deploy_key
          chmod 600 ~/.ssh/deploy_key
          rsync -avz -e "ssh -i ~/.ssh/deploy_key -o StrictHostKeyChecking=no" \
            show/static/ ${{ secrets.VPS_USER }}@${{ secrets.VPS_HOST }}:/var/www/run/
```

---

## 自动化（GitHub Actions）

- **sync.yml**：每日 10:00 北京时间运行 `main.py` + `activity_advice.py`，同步 Strava 活动并生成单次跑步点评。
- **weekly_report.yml**：每周日 23:00 北京时间运行 `analysis.py`，生成当周周报。
- **backfill_history.yml**：仅支持手动触发（workflow_dispatch），运行 `history_backfill.py` 做历史回填。

确保仓库已配置上述 Actions Secrets（至少 4 个 Strava/Google + 1 个 Gemini），否则工作流会因缺少凭证而失败。

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
