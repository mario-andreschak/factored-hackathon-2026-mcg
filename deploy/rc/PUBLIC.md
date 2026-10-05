# Public fictional RC

The separate `savia-rc-2026` Fly app runs the Python customer application,
informational inquiry team, and current Node voice application. It generates
new current-date fictional data inside its encrypted `rc_data` volume. No
organizer dataset, local session, signing key or existing ledger is copied.

The public fictional demonstration code is `SAVIA-2026`. Use it at the entry
gate and customer profile login. Accounts, movements and intake are simulated;
provider completions and voice calls use the configured real provider.

`public-gateway.mjs` signs an eight-hour visitor cookie and injects the existing
private avatar gateway token only on its fixed loopback connection. Browser
code receives neither this token nor the provider key. The gateway exposes no
FLUJO control plane. Informational team suggestions do not execute bank actions.

Build only from a committed revision:

```powershell
python deploy/rc/build_public_context.py C:/temporary/fresh-rc-context --revision HEAD
docker build -f C:/temporary/fresh-rc-context/deploy/rc/Dockerfile.public -t registry.fly.io/savia-rc-2026:REVISION C:/temporary/fresh-rc-context
```

The exported source manifest pins Git revision, tree and individual file hashes.
It excludes local environment files, private directories, datasets and generated
state. Both UI builds occur inside the image. The image verifies original source
hashes before startup, and the runtime receipt additionally hashes served assets.
The image contains project-owned source; FLUJO's permitted hackathon revision is
recorded as a compatibility reference, not a built or executed dependency.

Stage the existing provider key through Fly secrets, push the image, then use
`fly deploy --app savia-rc-2026 --config deploy/rc/fly.public.toml --image IMAGE
--ha=false`. Keep the separate existing `flujo-factored-2026` machine and volume
unchanged. Preserve `rc_data` across subsequent releases; preparing over an
existing fictional instance is refused. The deployment supervisor terminates
the other children when any component exits.

The native voice client waits two continuous seconds of quiet. Resumed speech
before that deadline remains one utterance. This behavior has unit and browser
coverage; physical microphone behavior requires the deployed acceptance run.
