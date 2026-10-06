FROM registry.fly.io/savia-rc-2026@sha256:9aa240aa6fd4616e2f029d6667ea234aa7ec8f7c1c8e1eef7a918d640a1b8b9d
USER root
COPY retained-runtime.json verify_release_layer.py /tmp/release/
RUN python /tmp/release/verify_release_layer.py before
COPY application/ /srv/savia/
RUN python /tmp/release/verify_release_layer.py after
LABEL io.savia.source-revision="634aa5244374b3e105ef7864fa100530bab45ec2" \
      io.savia.qualified-source="634aa5244374b3e105ef7864fa100530bab45ec2" \
      io.savia.successor.scope="final-public-evidence-retain-accepted-native-and-browser"
