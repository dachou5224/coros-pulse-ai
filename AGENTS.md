# Repository Guidelines

## Project Structure & Module Organization
`src/` 是数据流水线核心：`main.py` 负责同步 Strava 活动，`analysis.py` 生成周报，`activity_advice.py` 与 `coach.py` 生成 LLM 点评，`history_backfill.py` 用于历史回填。`scripts/export_static_data.py` 负责把 `Weekly_Report` 和 `Activities` 导出到 `show/static/data/` 的同源 JSON 快照。`show/` 是展示层，包含 Streamlit 页面、静态前端和训练计划对齐逻辑。模板位于 `card_template/`，训练计划数据位于 `data/training/`，长文档位于 `docs/`。除非需求同时跨越数据与展示链路，否则不要同时修改 `src/` 和 `show/`。

## Build, Test, and Development Commands
- `python -m venv .venv && source .venv/bin/activate`：创建本地虚拟环境。
- `pip install -r requirements.txt`：安装本地运行与 CI 所需的完整依赖。
- `python src/main.py`：执行 Strava 到 Google Sheets 的同步。
- `python src/analysis.py`：生成周报并按配置写入教练点评。
- `python src/history_backfill.py`：回填历史周报数据。
- `python scripts/export_static_data.py`：导出静态站同源 JSON 快照到 `show/static/data/`。
- `streamlit run src/app.py`：启动 Pulse 看板。
- `streamlit run show/app.py`：启动公开周报展示页。
- `cd show/static && python -m http.server 8080`：本地预览静态页。
- `python -m compileall -q src show`：执行与 CI 一致的轻量语法检查。

## Coding Style & Naming Conventions
代码应兼容 Python 3.12，即使部分本地环境版本更低。遵循 PEP 8：4 空格缩进，函数与模块使用 `snake_case`，环境变量使用 `UPPER_SNAKE_CASE`，辅助函数命名要短且明确。指标计算优先拆成小型纯函数，外部 I/O 尽量集中在脚本入口附近。不要硬编码密钥、表格 ID 或 API Token。

## Testing Guidelines
当前还没有完整测试套件，现有验证主要依赖脚本级运行、静态快照导出和 CI 的 `compileall` 检查。新增测试时，按 `test_*.py` 命名并尽量靠近被改模块，参考现有的 `src/test_coach.py`。提交 PR 前，至少运行相关脚本以及 `python -m compileall -q src show`；如果改动涉及看板，还应本地 smoke test `show/app.py` 或 `show/static/index.html`。

## Commit & Pull Request Guidelines
最近提交历史采用 Conventional Commit 风格，例如 `fix(ci): ...`、`feat(activity_advice): ...`、`fix(llm): ...`，后续继续保持。PR 说明应明确受影响链路，如 `sync`、`weekly report`、`show` 或 `deploy`，并写清所需环境变量或 Secrets 变更、验证命令，以及界面改动截图。若会影响 Google Sheets、Strava 或 VPS 部署，必须显式注明。

## Security & Configuration Tips
敏感信息只能放在 `.env`、Streamlit secrets 或 GitHub Actions secrets 中。以 `.env.example` 作为模板，不要提交真实凭证，也不要在脚本日志或 workflow 输出中打印密钥内容。
