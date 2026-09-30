# syntax=docker/dockerfile:1
FROM node:22-bookworm-slim AS ui-build
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.ts tsconfig.json ./
COPY src ./src
COPY public ./public
RUN npm run build

FROM python:3.13-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BANKING_DATA_DIR=/banking-data \
    BANKING_CONFIG_FILE=/banking-config/frontend.json \
    BANKING_STATE_DIR=/banking-state
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 banking \
    && useradd --uid 10001 --gid banking --no-create-home banking \
    && mkdir -p /banking-state \
    && chown banking:banking /banking-state
COPY server ./server
COPY --from=ui-build /build/dist ./dist
USER banking
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).read()"]
CMD ["python", "-m", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
