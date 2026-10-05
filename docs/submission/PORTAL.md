# One public submission portal

[Open the Savia submission](https://savia-rc-2026.fly.dev/submission/): six-slide
pitch, public GitHub, the final-video placeholder with the existing frozen film,
and a refreshed public development timeline. The review route, evidence map,
ElevenLabs comparison, `llms.txt` and JSON manifest are linked from the same page.

## Rebuild

```powershell
python scripts/build_submission_portal.py
node --test deploy/rc/submission-portal.test.mjs deploy/rc/public-gateway.test.mjs
python -m http.server 43827 --bind 127.0.0.1 --directory web
```

Open `http://127.0.0.1:43827/submission/`. The build copies only named public
documents, the six-slide final pitch, English captions, and the existing fictional
product screenshot. It never invokes the private development-history collectors.
Generated public files are committed so the immutable production build needs no
history access or extra library.

The public gateway serves `/submission/` before the fictional demo entry gate.
It accepts only GET/HEAD and serves exactly the files named in the public portal
manifest, verifying their SHA-256 on read. Private and unlisted paths are denied.
Demo authentication, origin enforcement, banking routes and WebSocket guards
retain their original boundaries. The production source exporter includes only
`web/submission/`, not the private history directory or general documentation tree.

To replace the final-video placeholder, edit the video slot and its manifest
status in `scripts/build_submission_portal.py` and `web/submission/index.html`,
then rebuild and publish an identified source revision. The frozen rc.2 film and
its receipts retain their original bytes and scope.
