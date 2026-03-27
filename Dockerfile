FROM python:3.12-slim

WORKDIR /app

# 中文展示用字体（与 chem_portal 类似，避免图表/界面缺字）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-wqy-microhei \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY . .

EXPOSE 8501

# 默认启动周报展示（无需 GCP）；Pulse 看板由 docker-compose 覆盖 command
CMD ["streamlit", "run", "show/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--browser.gatherUsageStats=false"]
