# ---- 前端构建（Vue3 + Vite） ----
FROM node:22-alpine AS frontend

# 国内服务器构建时 npm 直连很慢，默认走 npmmirror；海外机器可覆盖成官方源
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry $NPM_REGISTRY

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# ---- 运行时 ----
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/data/cache/hf

WORKDIR /app

# sentence-transformers 会拉 torch，这里显式指定 CPU 源，避免下载 CUDA 版本（镜像能小 1GB+）
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 国内机器可加 --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_INDEX_URL=""
RUN if [ -n "$PIP_INDEX_URL" ]; then \
        pip install --index-url "$PIP_INDEX_URL" \
                    --extra-index-url https://download.pytorch.org/whl/cpu \
                    -r requirements.txt; \
    else \
        pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt; \
    fi

COPY tcmqa ./tcmqa
COPY --from=frontend /frontend/dist ./frontend/dist
COPY scripts ./scripts
COPY data/golden_set.jsonl ./data/golden_set.jsonl

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "tcmqa.main:app", "--host", "0.0.0.0", "--port", "8000"]
