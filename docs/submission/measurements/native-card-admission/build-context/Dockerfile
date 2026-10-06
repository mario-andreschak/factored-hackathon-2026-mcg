FROM registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c
USER root
COPY expected-server-runtime.json verify_server_layer.py /tmp/card-admission-release/
RUN python /tmp/card-admission-release/verify_server_layer.py before c086702b39c483f92958f0b78e63cdab0146e40ab538c413ea44ad004301cd8c
COPY application/frontend/server/conversation.py /srv/savia/frontend/server/conversation.py
COPY application/resources/dispute_workflow.flow.json /srv/savia/resources/dispute_workflow.flow.json
COPY application/source-manifest.json /srv/savia/source-manifest.json
RUN python /tmp/card-admission-release/verify_server_layer.py after c086702b39c483f92958f0b78e63cdab0146e40ab538c413ea44ad004301cd8c
LABEL io.savia.source-revision="f2fa597a481a87b5301531cf180f8f61d1f3ba70" \
      io.savia.browser-source="c44d416fcf1ab95bcb16c77651418e6570d79782" \
      io.savia.successor.scope="server-native-card-admission-only"
