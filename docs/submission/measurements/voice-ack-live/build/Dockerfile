FROM registry.fly.io/savia-rc-2026@sha256:44bc554cd82ad62db51d536d580df248cbb188d24732e7ec1ed8133617c632a0
USER root
COPY expected-ui-runtime.json verify_ui_layer.py browser-build-provenance.json /tmp/ui-release/
RUN python /tmp/ui-release/verify_ui_layer.py before 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9
RUN python /tmp/ui-release/verify_ui_layer.py remove-ui 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9
COPY application/ /srv/savia/
COPY browser-dist/ /srv/savia/frontend/dist/
RUN python /tmp/ui-release/verify_ui_layer.py after 3d200c1f58957b3b3a032dbde642633e6c34eee70c7bee26734cdf0e1d137dd9
LABEL io.savia.source-revision="c44d416fcf1ab95bcb16c77651418e6570d79782" \
      io.savia.browser-source="c44d416fcf1ab95bcb16c77651418e6570d79782" \
      io.savia.successor.scope="reviewed-ui-ack-rejection-recovery"
