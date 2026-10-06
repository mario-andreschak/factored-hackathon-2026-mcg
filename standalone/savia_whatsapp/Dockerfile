FROM node:22-bookworm-slim AS whatsapp
WORKDIR /mcp
ENV PUPPETEER_SKIP_DOWNLOAD=true
COPY whatsapp-mcp/package*.json ./
RUN npm ci --no-audit --no-fund
COPY whatsapp-mcp/ ./
RUN npm run build
RUN node -e "Promise.all([import('@whiskeysockets/baileys'),import('better-sqlite3')]).then(([,sqlite])=>{new sqlite.default(':memory:').close()})"

FROM python:3.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tini libstdc++6 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=whatsapp /usr/local/bin/node /usr/local/bin/node
COPY --from=whatsapp /mcp /opt/whatsapp-mcp
WORKDIR /app
COPY requirements-dispute.txt requirements-pipeline.txt requirements-s3.txt ./
COPY frontend/requirements.txt frontend/requirements.txt
COPY standalone/savia_whatsapp/requirements.txt standalone/savia_whatsapp/requirements.txt
RUN python -m pip install --no-cache-dir -r standalone/savia_whatsapp/requirements.txt
COPY . .
RUN python -c "import hashlib,json,pathlib; m=json.loads(pathlib.Path('standalone-package.json').read_text()); assert all(hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()==h for p,h in m['files'].items())"
RUN useradd --create-home --uid 1000 savia && mkdir -m 700 /state && chown savia:savia /state
USER savia
ENV PYTHONUNBUFFERED=1
EXPOSE 43980
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "standalone.savia_whatsapp", "serve", "--state", "/state", "--mcp-dir", "/opt/whatsapp-mcp", "--backend", "baileys", "--container"]
