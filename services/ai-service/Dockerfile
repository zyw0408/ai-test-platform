FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY workers/ui-runner/package.json ./workers/ui-runner/package.json
RUN cd /app/workers/ui-runner && npm install
RUN cd /app/workers/ui-runner && npx playwright install --with-deps chromium

COPY services/ai-service ./services/ai-service
COPY workers/api-runner ./workers/api-runner
COPY workers/ui-runner ./workers/ui-runner

RUN pip install -e ./services/ai-service
RUN pip install -e ./workers/api-runner
RUN python -m compileall -q /app/services/ai-service/app
RUN python -m compileall -q /app/workers/api-runner/src

ENV AI_SERVICE_HOST=0.0.0.0
ENV AI_SERVICE_PORT=8000
ENV AI_SERVICE_STORAGE_DIR=/data
ENV AI_SERVICE_ARTIFACTS_DIR=/data/artifacts
ENV AI_SERVICE_DB_PATH=/data/platform.db
ENV AI_SERVICE_NODE_BIN=node
ENV AI_SERVICE_UI_RUNNER_DIR=/app/workers/ui-runner

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "services/ai-service", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
