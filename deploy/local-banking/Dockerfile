FROM flujo-slack-worker:turn-provenance-20260930
USER root
ARG QUALIFIED_NEXT_SHA256
COPY .artifacts/next.tar /tmp/qualified-banking-next.tar
COPY qualify.mjs /tmp/qualify-local-banking.mjs
RUN node /tmp/qualify-local-banking.mjs "${QUALIFIED_NEXT_SHA256}" \
    && rm /tmp/qualified-banking-next.tar /tmp/qualify-local-banking.mjs
COPY entrypoint.sh /usr/local/bin/banking-local-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/banking-local-entrypoint.sh \
    && chmod 0755 /usr/local/bin/banking-local-entrypoint.sh
ENV BANKING_POLICY_SHA256=a30e69338666e2605cefa7385c7c5d55cf3464314c6bd336b8f2566d1ca646af
LABEL io.flujo.local.repair="banking-adapter-and-startup-policy-20260930"
ENTRYPOINT ["/usr/local/bin/banking-local-entrypoint.sh"]
CMD ["node", "scripts/launch-next.mjs", "start", "-p", "4200", "-H", "0.0.0.0"]
