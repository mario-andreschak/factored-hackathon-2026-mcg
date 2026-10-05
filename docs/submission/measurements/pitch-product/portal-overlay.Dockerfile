# Publish only the public pitch assets over the exact accepted card runtime.
FROM registry.fly.io/savia-rc-2026@sha256:c38f3af736defdf55c7de47b0e1597ad361b3f748c845176b920377fd12b307f
USER root
COPY web/submission/ /srv/savia/web/submission/
COPY portal-source-manifest.json /srv/savia/portal-source-manifest.json
RUN node -e "const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');const root='/srv/savia/web/submission';const files=JSON.parse(fs.readFileSync(path.join(root,'portal-manifest.json'),'utf8')).files;for(const [name,want] of Object.entries(files)){if(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')!==want)throw new Error('Public asset integrity failure: '+name)}"
ARG PORTAL_REVISION
LABEL io.savia.portal-revision="${PORTAL_REVISION}" \
      io.savia.portal.scope="public-product-pitch-assets"
# Inherit the accepted application, native runtime and startup. No app rebuild.
