# One container serving the Flask API and the built React frontend.
# Cloud Run sets PORT; everything else comes from --set-env-vars at deploy time.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    ENVIRONMENT=production \
    LOG_LEVEL=WARNING \
    LOG_CHAT_SESSIONS=False \
    ENABLE_SECURITY=True \
    ENABLE_RATE_LIMITING=True \
    ENABLE_CORS=True \
    ENABLE_STATISTICS=True \
    ENABLE_PROMPT_INJECTION_DETECTION=True

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first so a code change does not reinstall them.
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Build the frontend, then keep only the built output.
COPY frontend/ /tmp/frontend/
WORKDIR /tmp/frontend
RUN npm ci && npm run build

COPY backend/ /app/backend/
WORKDIR /app/backend
RUN mkdir -p logs data static && \
    cp -r /tmp/frontend/dist/* static/ && \
    rm -rf /tmp/frontend

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/api/v2/health || exit 1

EXPOSE 8080

CMD exec gunicorn --bind 0.0.0.0:${PORT:-8080} \
    --workers 1 \
    --worker-class sync \
    --timeout 120 \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile - \
    --log-level info \
    wsgi:app
