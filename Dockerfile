# Finsona AI — single-container deployment (E16-05).
#   docker build -t finsona .
#   docker run -p 8000:8000 -v finsona-data:/data finsona      -> http://localhost:8000
# Set FINSONA_STORAGE_KEY / FINSONA_SECRET_KEY to supply your own keys; otherwise they are
# generated once into the /data volume. FINSONA_DEMO_MODE=false hides demo logins and reset.

FROM node:22-slim AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
COPY backend/openapi.json /src/backend/openapi.json
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 \
    FINSONA_DATABASE_URL=sqlite:////data/finsona.db \
    FINSONA_STORAGE_DIR=/data/storage \
    FINSONA_SNAPSHOT_DIR=/data/snapshot \
    FINSONA_LLM_CACHE_FILE=/data/llm_cache.json \
    FINSONA_CORS_ORIGINS=[]
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY data /app/data
COPY --from=web /src/frontend/dist /app/frontend/dist
COPY scripts/docker-entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh && useradd -r -u 10001 finsona \
    && mkdir /data && chown -R finsona /data /app/data
USER finsona
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
ENTRYPOINT ["/entrypoint.sh"]
