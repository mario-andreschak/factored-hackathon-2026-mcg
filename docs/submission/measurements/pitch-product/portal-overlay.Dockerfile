# Publish only the public pitch assets over the exact accepted card runtime.
FROM registry.fly.io/savia-rc-2026@sha256:c38f3af736defdf55c7de47b0e1597ad361b3f748c845176b920377fd12b307f
USER root
COPY apply_portal_manifest.py /tmp/apply_portal_manifest.py
RUN python /tmp/apply_portal_manifest.py verify-base
COPY web/submission/ /srv/savia/web/submission/
COPY portal-source-manifest.json /srv/savia/portal-source-manifest.json
RUN python /tmp/apply_portal_manifest.py apply
ARG PORTAL_REVISION
LABEL io.savia.portal-revision="${PORTAL_REVISION}" \
      io.savia.portal.scope="public-product-pitch-assets"
# Inherit the accepted application, native runtime and startup. No app rebuild.
