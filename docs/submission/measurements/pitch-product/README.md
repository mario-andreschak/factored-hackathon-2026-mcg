# Product pitch publication

The six-slide product pitch, human-first README and public portal follow the requested Why → What → How story. Card protection, ElevenLabs positioning and the ten-team narration use the requested copy; presenter notes separate **Say** and **If asked**.

The live [submission portal](https://savia-rc-2026.fly.dev/submission/) serves the frozen public assets from portal source `4a7341209e56fd66468774316a0cc5883172e426`. Application source remains `f3c57b26d07c1e96b6e61a25befcbbc5fd51a17f`. The publication image is `registry.fly.io/savia-rc-2026@sha256:75fda1618ec9c48a77c46e00573a51c4f0a86e780a5349e4e5cba38ad72f2517`.

## Publication checks

- [Deployment receipt](deployment-receipt.json): healthy machine, retained configuration equality, and all 27 public HTTP asset bodies matched against immutable Git bytes.
- [Runtime verification](runtime-verification.json): all 177 composite source hashes checked; 149 nonportal source files, 22 built customer-browser assets and four native runtime files matched the accepted application receipt.
- [Artifact audit](artifact-audit.json): six native slides and PDF pages, 100 editable team markers, exact requested narration, one README limits section, resolved source paths, and six original frozen media files unchanged.
- [CI at presentation source 476c88e0](code-ci-476c88e0.json): all eleven PR checks passed on a tested merge tree identical to that source tree. The separate push-run timing result is retained in the same audit receipt.
- [Earlier frozen application publication CI](code-ci-b4d83b53.json): all eleven hosted jobs passed at its own source pin.

These publication checks read source hashes, configuration equality and public assets. They do not repeat customer bank, model or voice calls; the existing acceptance and workload receipts retain their own source and observation pins.

## Source integrity

The [overlay Dockerfile](portal-overlay.Dockerfile) inherits the exact accepted application image. The [manifest helper](apply_portal_manifest.py) verifies all base sources before copying the public portal. It then updates exactly 28 portal entries, rejects stale or unreferenced files, preserves every nonportal hash, and verifies the complete composite source map. The startup integrity guard is unchanged. Application and portal revisions are recorded as separate components.

The first publication attempt updated portal assets without updating their guarded source hashes. The runtime correctly rejected that image; the accepted image was restored. The corrected publication passed the retained guard and the independent checks above. This startup result is publication evidence, separate from customer-path acceptance.
