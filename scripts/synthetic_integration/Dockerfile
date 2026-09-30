# Remote-only derived fixture image. Original package source remains present.
FROM restored-package
USER root
COPY bundle/banking/ /opt/fixture-bank/
COPY bundle/frontend/ /opt/fixture-front/frontend/
RUN python3 -m venv /opt/fixture-bank/.venv \
    && /opt/fixture-bank/.venv/bin/pip install --no-cache-dir -r /opt/fixture-bank/requirements-mcp.txt \
    && /opt/fixture-bank/.venv/bin/pip check \
    && python3 -m venv /opt/fixture-front/.venv \
    && /opt/fixture-front/.venv/bin/pip install --no-cache-dir -r /opt/fixture-front/frontend/requirements.txt \
    && /opt/fixture-front/.venv/bin/pip install --no-cache-dir rfc8785==0.1.4 \
    && /opt/fixture-front/.venv/bin/pip check
COPY bundle/fixture/ /opt/integration/fixture/
COPY harness/ /opt/integration/harness/
RUN mkdir -p /run/review
ARG FIXTURE_SOURCE
ARG FRONTEND_GATE_SOURCE
ARG SCENARIO_MODE
LABEL io.flujo.integration.scope="derived-fictional-no-model-assembly" \
      io.flujo.integration.fixture.source="$FIXTURE_SOURCE" \
      io.flujo.integration.frontend.source="$FRONTEND_GATE_SOURCE"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/integration/harness:/opt/integration/fixture:/opt/fixture-front \
    SCENARIO_MODE="$SCENARIO_MODE"
WORKDIR /opt/integration/harness
USER node
ENTRYPOINT ["/opt/fixture-front/.venv/bin/python", "/opt/integration/harness/inside.py"]
CMD []
