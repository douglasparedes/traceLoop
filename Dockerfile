# TraceLoop — single-service image for Coolify.
# Stage 1 builds the PWA; stage 1b builds the Remotion video bundle;
# stage 2 runs the API + serves the built frontend from the same origin
# (manifest/SW/API share one scope).
FROM node:22-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Remotion video bundle (prebuilt so first render doesn't pay bundling).
FROM node:22-alpine AS videobuild
WORKDIR /vbuild
COPY video/package.json video/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY video/ ./
RUN npm run bundle

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FRONTEND_DIST=/app/frontend/dist \
    VIDEO_BUNDLE_DIR=/app/video/bundle \
    DATABASE_URL=sqlite:////data/fieldguard.db
# Node.js (Remotion render) + headless-Chromium shared libraries.
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=frontend /build/dist /app/frontend/dist
COPY --from=videobuild /vbuild/bundle /app/video/bundle
COPY --from=videobuild /vbuild/render.mjs /vbuild/asset-server.mjs /vbuild/package.json /app/video/
COPY --from=videobuild /vbuild/node_modules /app/video/node_modules
RUN mkdir -p /data /app/backend/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/api/health', timeout=4)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
