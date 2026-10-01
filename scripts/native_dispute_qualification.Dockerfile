FROM flujo-banking-builder:local
WORKDIR /app
COPY flujo/ /app/
COPY qualification/native_dispute_qualification.ts /app/dispute-qualification-adapter.ts
ENV FLUJO_EXECUTION_ADAPTER_MODULE=/app/dispute-qualification-adapter.ts
RUN NODE_OPTIONS=--max-old-space-size=4096 npm run build
# Restore only immutable public source after generated Next typing updates.
COPY flujo/ /app/
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip python3-venv && rm -rf /var/lib/apt/lists/*
ENV PIP_BREAK_SYSTEM_PACKAGES=1
COPY qualification/requirements-dispute.txt /tmp/requirements-dispute.txt
COPY qualification/frontend/requirements.txt /tmp/frontend/requirements.txt
COPY qualification/requirements-pipeline.txt qualification/requirements-s3.txt /tmp/
RUN python3 -m pip install --no-cache-dir -r /tmp/requirements-dispute.txt
COPY qualification/requirements-mcp.txt /tmp/requirements-mcp.txt
COPY qualification/dispute_workflow /qualification/dispute_workflow
COPY qualification/resources /qualification/resources
COPY qualification/config /qualification/config
COPY qualification/contracts /qualification/contracts
COPY qualification/banking_mcp /qualification/banking_mcp
COPY qualification/frontend/server /qualification/frontend/server
COPY qualification/pipeline /qualification/pipeline
COPY qualification/.gitattributes /qualification/.gitattributes
COPY qualification/graph_config_v3.yaml /qualification/graph_config_v3.yaml
COPY qualification/native_dispute_qualification.py /qualification/native_dispute_qualification.py
COPY qualification/qualify_dispute.py /qualification/qualify_dispute.py
COPY qualification/native_dispute_capability_probe.mjs qualification/native_dispute_bridge_loader.mjs qualification/native_dispute_compatibility_probe.mjs /qualification/
COPY qualification/native_dispute_revocation_probe.mjs /qualification/
COPY qualification/build_dispute_graph.mjs qualification/native_dispute_qualification.mjs qualification/native_dispute_qualification.Dockerfile /qualification/
COPY qualification/bin /qualification/bin
RUN chmod 0555 /qualification/bin/codex
COPY source-manifest.json /qualification/source-manifest.json
LABEL org.opencontainers.image.revision="0ba62296520a505e6d71eddf5aa650691f3dc311" io.flujo.dispute.scope="isolated-qualification"
ENV NODE_ENV=production FLUJO_DATA_DIR=/runtime/data FLUJO_APP_ROOT=/app FLUJO_CONTAINER=1 HOSTNAME=0.0.0.0 PORT=4200
ENTRYPOINT ["node", "scripts/launch-next.mjs", "start"]
