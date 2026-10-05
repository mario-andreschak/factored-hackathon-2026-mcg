# syntax=docker/dockerfile:1
ARG FRONTEND_IMAGE=hackathon-banking-frontend:local
ARG WORKER_IMAGE=flujo-slack-worker:turn-provenance-20260930
FROM ${FRONTEND_IMAGE} AS frontend
FROM ${WORKER_IMAGE}
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu tini python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY --from=frontend /app/requirements.txt /opt/savia/requirements.txt
RUN python3 -m venv /opt/savia/.venv \
    && /opt/savia/.venv/bin/pip install --no-cache-dir -r /opt/savia/requirements.txt
COPY --from=frontend /app/server /opt/savia/server
COPY --from=frontend /app/dist /opt/savia/dist
COPY deploy/fly/entrypoint.sh deploy/fly/runtime.mjs deploy/fly/gateway.mjs /opt/savia/fly/
RUN sed -i 's/\r$//' /opt/savia/fly/entrypoint.sh \
    && chmod 0755 /opt/savia/fly/entrypoint.sh
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=16m --retries=5 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:8080/_fly/health',{headers:{host:process.env.FLUJO_FLY_MAIN_HOST||'flujo-factored-2026.fly.dev'},signal:AbortSignal.timeout(4000)}).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
ENTRYPOINT ["tini", "--", "/opt/savia/fly/entrypoint.sh"]
CMD ["node", "/opt/savia/fly/runtime.mjs"]
