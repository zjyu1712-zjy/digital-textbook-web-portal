FROM node:24-bookworm-slim AS javascript
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
WORKDIR /build
COPY package.json ./
RUN npm install --omit=dev --ignore-scripts

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-cjk fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt package.json ./
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
COPY --from=javascript /build/node_modules ./node_modules
RUN node --version && node -e "require('playwright')"
RUN pip install --no-cache-dir -r requirements.txt \
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
