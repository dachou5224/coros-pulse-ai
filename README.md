# coros-pulse-ai

基于 Strava 与 Google Sheets 的跑步数据同步与周报分析流水线：拉取活动、计算 TRIMP/CTL/TSB/VDOT 等指标并写入周报表，另提供 Streamlit 看板读取同一张表做展示。

---

## 功能概览

- **Strava 同步**（`src/main.py`）：定时拉取 Strava 活动，写入 Google Sheet「Coros_Running_Data」的 Activities 表，含每公里 splits（配速、心率）的 JSON。
- **周报分析**（`src/analysis.py`）：按周汇总跑量、计算 TRIMP/CTL/ATL/TSB、VDOT、LSD 解耦率等，写入同一 Sheet 的 **Weekly_Report** 表；可选调用 Gemini 生成本周教练点评与单次跑步点评（写入 Weekly_Report 的 Coach Advice 列与 **Activity_Advice** 表）。
- **历史回填**（`src/history_backfill.py`）：手动一次性按历史数据生成完整周报（用于首次建表或补全）。
- **Streamlit 看板**（`src/app.py`）：从同一 Sheet 的 Weekly_Report 读数据（gspread + Secrets），展示核心看板、历史与指标说明。
- **周期训练周报展示**（`show/app.py`）：从 Weekly_Report 的 CSV URL 读数据（无需 GCP 凭证），展示 PMC、TSB、VDOT、LSD 解耦等；可选环境变量 `WEEKLY_REPORT_CSV_URL` 覆盖默认链接。周报在 Sheet 侧约**每周**更新，Streamlit 对 CSV 的默认缓存为 **24 小时**（`WEEKLY_REPORT_CSV_CACHE_TTL_SEC`），以减少对 Google 的请求。

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
│   ├── sync.yml             # 每日同步 + 单次点评
│   ├── weekly_report.yml    # 每周周报
│   ├── backfill_history.yml # 手动回填
│   ├── ci.yml               # PR / push 语法检查
│   └── deploy.yml           # push main → VPS docker compose
├── requirements.txt          # 全量依赖（含 playwright/html2image，供本地与 Actions 脚本）
├── requirements-docker.txt   # Streamlit 镜像用精简依赖
├── Dockerfile
├── docker-compose.yml        # VPS / 本地：coros-show（默认）+ 可选 profile pulse
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
- Streamlit 看板（`src/app.py`）使用 **Streamlit Secrets**：在 `.streamlit/secrets.toml` 中配置 `gcp_service_account`（或云平台提供的 Secrets），用于读 Sheet。**勿将 `secrets.toml` 提交到仓库。** 读 **Weekly_Report** 的默认缓存为 **24 小时**（`PULSE_WEEKLY_CACHE_TTL_SEC`，秒），与「周报周更」节奏一致，减少 gspread / Sheets API 调用；需要更快刷新时可改小该值。
- 周期训练周报展示（`show/app.py`）**可选**环境变量：`WEEKLY_REPORT_CSV_URL`（Weekly Report 表 CSV 导出链接，不设则使用代码内默认公开链接）；`WEEKLY_REPORT_CSV_CACHE_TTL_SEC`（CSV HTTP 缓存秒数，默认 86400）。
- **教练点评**（`src/analysis.py` 调用 `src/coach.py`）：使用 OpenAI 兼容方式调用 Google Gemini，生成本周教练点评与单次跑步点评。可选环境变量（见 `.env.example`）：`API_KEY`（或 `GOOGLE_API_KEY` / `GEMINI_API_KEY`）、`BASE_URL`（如 `https://generativelanguage.googleapis.com/v1beta/openai`，勿带尾部斜线）、`COACH_MODEL` 或 `MODEL_NAME`（默认 `gemini-2.0-flash`）、`LLM_DELAY_SECONDS`。未配置时周报仍会写入，Coach Advice 列为「暂无」。

### GitHub Actions Secrets（仓库 Settings → Secrets and variables → Actions）

以下为工作流里**实际引用**的 Repository secrets（名称需与表中完全一致）。**不要**把密钥写进 Git 提交，只在 GitHub 网页里配置。

| Secret 名称 | 被哪些 workflow 使用 | 内容说明 | 是否必需 |
|-------------|----------------------|----------|----------|
| `STRAVA_CLIENT_ID` | sync.yml | Strava 应用 Client ID | 跑 sync 则 ✅ |
| `STRAVA_CLIENT_SECRET` | sync.yml | Strava Client Secret | 跑 sync 则 ✅ |
| `STRAVA_REFRESH_TOKEN` | sync.yml | Strava Refresh Token | 跑 sync 则 ✅ |
| `GOOGLE_JSON_KEY` | sync.yml、weekly_report.yml、backfill_history.yml | Google 服务账号 **JSON 整段**（单行粘贴），脚本里映射为 `GOOGLE_APPLICATION_CREDENTIALS_JSON` | 跑上述任一则 ✅ |
| `API_KEY` | sync.yml（activity_advice）、weekly_report.yml | Gemini / OpenAI 兼容 API Key；与 `GEMINI_API_KEY` **二选一** | 要生成教练点评则 ✅ |
| `GEMINI_API_KEY` | 同上 | 同上，任选其一即可 | 同上 |
| `VPS_HOST` | deploy.yml | VPS 公网 IP 或域名 | 要自动部署则 ✅ |
| `VPS_USER` | deploy.yml | SSH 登录用户名（如 `root`） | 要自动部署则 ✅ |
| `VPS_KEY` | deploy.yml | SSH **私钥**全文（PEM，含 `BEGIN`/`END` 行） | 要自动部署则 ✅ |

**说明**：

- `API_KEY` 与 `GEMINI_API_KEY` 只配一个即可；都不配时周报仍会写入 Sheet，但 Coach Advice / 单次点评不会调用 LLM。
- **ci.yml** 不读取任何 Secrets。
- **deploy.yml** 不配 `VPS_*` 时，仅 deploy 任务失败；**sync / weekly / backfill 不受影响**。
- Streamlit Pulse 的 `gcp_service_account` 在 **VPS 上的** `.streamlit/secrets.toml` 配置，**不是** GitHub Secret（除非改用其它托管方式自行注入）。

本地开发时，参考 `.env.example` 配置 `.env`（已加入 `.gitignore`），包含：

- **Gemini**：`API_KEY`、`BASE_URL`、`COACH_MODEL`、`LLM_DELAY_SECONDS`
- **Google Sheet**：`GOOGLE_APPLICATION_CREDENTIALS_JSON`（或 `GOOGLE_APPLICATION_CREDENTIALS_FILE`）
- **跑者画像**（可选）：`RUNNER_GENDER`、`RUNNER_AGE`、`RUNNER_GOAL_RACE`、`RUNNER_GOAL_TIME`、`RUNNER_INJURY_HISTORY`
- **卡片生成**（可选）：`ENABLE_CARD_RENDER`、`CARD_BRAND_TAG`

跑者画像、BASE_URL 等 **未** 在 Actions 中配置；CI 不设则脚本内用默认值。

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

#### VPS 部署（静态首页 + Nginx）

**路径约定（当前环境）**

| 用途 | VPS 路径 |
|------|----------|
| 本仓库（Docker / git pull） | `/root/coros-pulse-ai` |
| 静态首页（`show/static/` → Nginx `root`） | `/var/www/run-home` |

将 `show/static/` 部署到 VPS，配合 Nginx 作为独立子站。以下步骤不涉及任何私密信息，仅作流程说明。

**前置条件**：已有一台 VPS、域名已解析到该 VPS 的 IP。

**1. 创建目录并同步文件**

```bash
# 在 VPS 上创建目录（以 root 或 sudo 执行）
sudo mkdir -p /var/www/run-home
sudo chown $USER:$USER /var/www/run-home

# 本地执行：将 show/static/ 下所有文件同步到 VPS
rsync -avz --delete show/static/ user@YOUR_VPS_IP:/var/www/run-home/

# 或使用 scp
scp -r show/static/* user@YOUR_VPS_IP:/var/www/run-home/
```

**2. Nginx 配置**

在 VPS 上创建 `/etc/nginx/sites-available/run`（将 `run.nice-ai.dev` 替换为你的域名）：

```nginx
server {
    listen 80;
    server_name run.nice-ai.dev;
    root /var/www/run-home;
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

**4. 自动部署**

push 到 `main` 且变更命中 `deploy.yml` 配置的路径时，**`.github/workflows/deploy.yml`** 会 SSH 到 VPS：在 **`/root/coros-pulse-ai`** 执行 `git pull` + `docker compose up -d --build`，并把 **`show/static/`** 同步到 **`/var/www/run-home`**（可用环境变量 **`COROS_STATIC_WEB_ROOT`** 覆盖目标目录）。所需 Secrets：`VPS_HOST`、`VPS_USER`、`VPS_KEY`（见上文「GitHub Actions Secrets」表）。

---

## 自动化（GitHub Actions）

- **sync.yml**：每日 10:00 北京时间运行 `main.py` + `activity_advice.py`，同步 Strava 活动并生成单次跑步点评。
- **weekly_report.yml**：每周日 23:00 北京时间运行 `analysis.py`，生成当周周报。
- **backfill_history.yml**：仅支持手动触发（workflow_dispatch），运行 `history_backfill.py` 做历史回填。
- **ci.yml**：push / PR 时安装 `requirements-docker.txt` 并对 `src/`、`show/` 做 `compileall` 语法检查。
- **deploy.yml**（与 `chem_portal/.github/workflows/deploy.yml` 同源模式）：向 `main` 推送且变更涉及 `src/`、`show/` 或 Docker 相关文件时，经 SSH 在 VPS 上 `git pull` + `docker compose up -d --build`。需在仓库 Secrets 中配置 **`VPS_HOST`**、**`VPS_USER`**、**`VPS_KEY`**（与 chem_portal 一致；勿在脚本中 `echo` 私钥全文）。

确保数据流水线 Secrets（至少 4 个 Strava/Google + 1 个 Gemini）已配置。**deploy** 与数据同步相互独立：未配 VPS 时仅 deploy 失败，不影响 sync/weekly。

### Docker 与 VPS 部署（deploy.yml）

1. **VPS 一次性准备**：安装 Docker 与 Compose；将本仓库 clone 到 **`/root/coros-pulse-ai`**（即 `DEPLOY_ROOT=/root` 且 `COROS_REPO_DIR=coros-pulse-ai`，与其它路径不一致时在 VPS 上设置这两项）。创建静态目录 **`/var/www/run-home`**（或自定义后设 **`COROS_STATIC_WEB_ROOT`**），Nginx 的 `root` 指向该目录。
2. **默认服务**：`docker compose up -d --build` 仅启动 **coros-show**（周报 Streamlit），宿主机端口 **8512**（避免与同机 chem_portal 的 8501 冲突）。
3. **Pulse 看板（可选）**：在 **`/root/coros-pulse-ai`** 下放置 **`.streamlit/secrets.toml`**，并在 VPS 上设置 **`COMPOSE_PROFILES=pulse`** 后再执行 compose，将额外启动 Pulse，映射 **8511**。
4. **环境变量**：可在 compose 同目录使用 `.env` 传入 `WEEKLY_REPORT_CSV_URL`、`WEEKLY_REPORT_CSV_CACHE_TTL_SEC`、`PULSE_WEEKLY_CACHE_TTL_SEC` 等。
5. **静态首页**：每次 deploy 在 VPS 上执行 `rsync`：`show/static/` → **`/var/www/run-home`**（或 `COROS_STATIC_WEB_ROOT`）。

本地构建：`docker compose up -d --build`；仅语法验证可参考 **ci.yml**。

---

## 与 coros-data-show 的关系

**原 coros-data-show 已合并至本仓库的 `show/` 目录**。若曾单独克隆 coros-data-show，可改为使用本仓的 `show/` 入口：`streamlit run show/app.py`。  
show 为**只读展示**：通过 Weekly_Report 的 CSV URL（或环境变量 `WEEKLY_REPORT_CSV_URL`）读数据，无需 GCP 凭证；默认 **24h** 缓存 CSV（`WEEKLY_REPORT_CSV_CACHE_TTL_SEC`）以降低对 Google 的请求频率。本仓 `src/` 负责**写** Sheet（同步 + 周报）。

---

## 数据与指标说明

- **Sheet 表名**：`Coros_Running_Data`（可在 `main.py` 中修改 `SHEET_NAME`）。
- **周报表**：`Weekly_Report`，含 Week Start/End、Distance、Weekly Load、Fitness (CTL)、Form (TSB)、VDOT、LSD Decouple、Status 等列。
- **指标含义**：见 `src/app.py` 内「指标百科」Tab，或本仓 `show/` 页面展示的周报结构。

每公里 splits 数据来自 Strava 活动详情的 `splits_metric`，已写入 Activities 表对应列的 JSON；若需更细粒度，可后续对接 Strava Streams API 按 1 km 分桶。
