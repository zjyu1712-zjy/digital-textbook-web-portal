FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm chromium fonts-noto-cjk fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt package.json ./
RUN pip install --no-cache-dir -r requirements.txt && npm install --omit=dev --ignore-scripts \
    && useradd --create-home --uid 10001 textbook
COPY portal ./portal
COPY static ./static
COPY skill ./skill
COPY tests/runtime-check.cjs ./tests/runtime-check.cjs
COPY scripts ./scripts
RUN mkdir -p /data && chown -R textbook:textbook /data /app
ENV PORTAL_DATA_DIR=/data PORTAL_SKILL_DIR=/app/skill BROWSER_EXECUTABLE=/usr/bin/chromium PLAYWRIGHT_MODULE=/app/node_modules/playwright
USER textbook
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "300", "--graceful-timeout", "20", "--access-logfile", "-", "portal.server:app"]
