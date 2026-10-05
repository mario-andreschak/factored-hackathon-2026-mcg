"""Regenerate the editable SVG deployment diagrams and self-contained viewer.

No credentials or record-level data are read by this generator. Architecture
facts were reviewed against the running Docker mounts and deploy/fly sources.
"""
from html import escape
from pathlib import Path
import json
from system_landscape import system_svg, system_section, standalone, DOCUMENT_CSS

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 2400, 1320
INK = '#18323d'
MUTED = '#57707c'
COLORS = {'request': '#2869b2', 'data': '#117f72', 'batch': '#b87412', 'state': '#8052a2'}


class Diagram:
    def __init__(self, title, subtitle):
        self.parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(subtitle)}</desc>
<defs>''']
        for key, color in COLORS.items():
            self.parts.append(f'<marker id="{key}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>')
        self.parts.append('''</defs><style>
text{font-family:Arial,Helvetica,sans-serif;fill:#18323d}
.title{font-size:43px;font-weight:700}.sub{font-size:22px;fill:#57707c}
.boundary{font-size:22px;font-weight:700;letter-spacing:.5px}
.kicker{font-size:17px;font-weight:700;letter-spacing:1.1px;fill:#57707c}
.node-title{font-size:27px;font-weight:700}.body{font-size:21px;fill:#365460}
.small{font-size:19px;fill:#57707c}.label{font-size:19px;font-weight:600}
.foot{font-size:21px;fill:#365460}
</style><rect width="2400" height="1320" fill="#f7fafb"/>''')
        self.text(45, 60, title, 'title')
        self.text(45, 100, subtitle, 'sub')

    def text(self, x, y, value, cls='body', anchor=None, color=None):
        attrs = (f' text-anchor="{anchor}"' if anchor else '') + (f' style="fill:{color}"' if color else '')
        self.parts.append(f'<text x="{x}" y="{y}" class="{cls}"{attrs}>{escape(value)}</text>')

    def rect(self, x, y, w, h, fill, stroke, radius=18, dashed=False):
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="2"'+ (' stroke-dasharray="10 7"' if dashed else '') + '/>')

    def boundary(self, x, y, w, h, title, fill='#edf3f6', stroke='#91a7b2', dashed=False):
        self.rect(x, y, w, h, fill, stroke, 22, dashed)
        self.text(x+25, y+35, title, 'boundary')

    def node(self, x, y, w, h, kicker, title, lines, kind='service', size=None):
        self.parts.append(f'<g data-node="{escape(title)}" data-box="{x},{y},{w},{h}">')
        fill, stroke = {'service':('#fff', '#91a7b2'), 'data':('#effaf6', '#6bb9a2'), 'external':('#f0f5fd', '#8baacf'), 'state':('#f7f0fb', '#b5a0c6'), 'batch':('#fff9ed', '#d3b27b')}[kind]
        self.rect(x,y,w,h,fill,stroke)
        self.text(x+22,y+30,kicker,'kicker')
        self.text(x+22,y+67,title,'node-title')
        for i, line in enumerate(lines):
            self.text(x+22,y+101+i*29,line,'body' if size is None else size)
        self.parts.append('</g>')

    def arrow(self, points, kind='request', two=False, dashed=False):
        d='M '+' L '.join(f'{x} {y}' for x,y in points)
        self.parts.append(f'<path d="{d}" fill="none" stroke="{COLORS[kind]}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" marker-end="url(#{kind})"' + (f' marker-start="url(#{kind})"' if two else '') + (' stroke-dasharray="9 7"' if dashed else '') + '/>')

    def label(self, x, y, lines, kind='request'):
        if isinstance(lines,str): lines=[lines]
        width=max(len(line) for line in lines)*10.1+22
        self.rect(x-width/2,y-22,width,len(lines)*24+8,'#f7fafb','#f7fafb',7)
        for i,line in enumerate(lines): self.text(x,y+i*24,line,'label','middle',COLORS[kind])

    def legend(self, status):
        self.text(45, 1208, 'READING THE ARROWS', 'kicker')
        entries=[(45,'request','Request ↔ response'),(465,'data','Data returned to reader'),(970,'batch','Batch / migration'),(1410,'state','Persistent state read / write')]
        for x,key,label in entries:
            self.arrow([(x,1235),(x+55,1235)],key,two=key in {'request','state'},dashed=key=='batch')
            self.text(x+74,1242,label,'small')
        self.text(45,1293,status,'small')

    def finish(self):
        return '\n'.join(self.parts)+ '\n</svg>\n'


def docker():
    d=Diagram('Docker · local deployment landscape', 'Separate containers on Docker Desktop; host ports are published on loopback only.')
    d.boundary(380,145,1595,1015,'LOCAL HOST · Windows workstation + Docker Desktop Linux VM')
    d.boundary(410,425,1535,345,'PRIVATE DOCKER NETWORK · flujo-slack_default', '#e8f0f7','#9eafc1',True)
    d.boundary(855,465,1060,280,'FLUJO WORKER CONTAINER', '#f0f4f8','#a8bac8')
    d.node(45,205,280,150,'EXTERNAL SOURCE','Organizer S3',['Read-only source CSVs','Customers + products'],'external')
    d.node(435,205,470,150,'OFFLINE · HOST PROCESS','DuckDB pipeline',['Bronze → silver → gold; rejects → quarantine','Publish CURRENT only after checks pass'],'batch',size='small')
    d.node(1110,205,805,150,'HOST FILES · SHARED READ-ONLY BINDS','Published snapshot · /banking-data',['CURRENT + manifests; silver customers/products; gold transaction shards','Same data/ directory mounted into Savia and the worker'],'data')
    d.node(45,525,280,190,'LOCAL USER','Browser / Savia',['http://localhost:43800','Runs the JS/CSS UI','Sends /api/* requests'],'external')
    d.node(435,525,325,190,'SAVIA CONTAINER','Savia API · :8080',['Serves UI assets + /api/*','Session → approved customer','DuckDB returns owned rows'],'service')
    d.node(975,525,350,190,'PRIVATE BACKEND','FLUJO · :4200',['Execution token + signed user','Pinned graph / restricted run','Sandbox :4201 stays internal'],'service')
    d.node(1515,525,360,190,'DATA ACCESS SERVICE','Banking MCP',['stdio; read-only customer tools','Checks product ownership','Masked facts + opaque handles'],'data')
    d.node(2100,350,260,175,'EXTERNAL COMPUTE','Model provider',['Codex / configured LLM','Prompt + minimized facts','Reply → FLUJO → Savia'],'external',size='small')
    d.node(2100,605,260,175,'SAME SOURCE S3','Optional recheck',['Only with verify_source','Pinned ETag HEAD / GET','No S3 writes'],'external',size='small')
    d.node(435,850,325,190,'FRONTEND VOLUME · RW','Frontend state',['/banking-state','Sessions + public chat history','Queued logout revocations'],'state')
    d.node(975,850,350,190,'worker-data VOLUME · RW','FLUJO state',['/data/flujo','Flows, models, credentials','Conversations + owner ledger'],'state')
    d.node(1515,850,360,190,'BANK VOLUMES · RW','Banking state',['/banking-state/banking.db','Handles + authorization state','Separate synthetic demo state'],'state')
    # Batch ingestion and publication.
    d.arrow([(325,275),(435,275)],'batch',dashed=True)
    d.arrow([(905,275),(1110,275)],'batch',dashed=True)
    d.label(1007,258,'publish', 'batch')
    # Data never travels through the browser or model as files.
    d.arrow([(1170,355),(1170,385),(595,385),(595,525)],'data')
    d.label(840,376,'Owned snapshot rows', 'data')
    d.arrow([(1710,355),(1710,525)],'data')
    d.label(1800,448,['Snapshot read','via DuckDB'],'data')
    # Requests and minimized replies.
    d.arrow([(325,620),(435,620)],two=True)
    d.label(380,584,['HTTP','43800 → 8080'])
    d.arrow([(760,620),(975,620)],two=True)
    d.label(867,579,['Private HTTP','signed identity'])
    d.arrow([(1325,620),(1515,620)],two=True)
    d.label(1420,590,['stdio MCP','signed run context'])
    d.arrow([(1290,525),(1290,405),(2045,405),(2045,425),(2100,425)],two=True)
    d.label(1920,397,'HTTPS / LLM')
    d.arrow([(1875,680),(2100,680)],'data',two=True,dashed=True)
    d.label(1987,646,['Bounded S3','verification'],'data')
    for x in (595,1150,1695):
        d.arrow([(x,715),(x,850)],'state',two=True)
        d.label(x,804,'read / write','state')
    d.text(435,1083,'PRIVATE CONFIG · RO host mounts → server signers, policy, S3 credentials; never sent to browser or model.', 'foot')
    d.text(435,1122,'OTHER ENTRY POINTS · Operator: localhost:43420 → UI proxy → worker. Slack → Socket Mode gateway → worker loopback.', 'small')
    d.text(45,174,'DATA ORIGIN', 'kicker')
    d.text(2100,174,'OUTBOUND ONLY', 'kicker')
    d.text(45,1130,'IMAGE STATUS', 'kicker')
    d.text(45,1160,'Banking adapter missing*', 'small')
    d.legend('* Recorded source Docker image: banking adapter missing; customer chat/revocation can fail. Configured topology · 30 Sep 2026.')
    return d.finish()


def fly():
    d=Diagram('Fly · hosted deployment landscape','One Fly Machine contains gateway, Savia, FLUJO and banking MCP; only gateway :8080 receives public traffic.')
    d.boundary(380,145,1595,225,'WORKSTATION / FIRST IMPORT · offline preparation; separate from the running Fly Machine', '#fcf7ec','#ccb27d',True)
    d.boundary(380,395,1595,765,'FLY APP · flujo-factored-2026 · iad · 1 Machine · 2 shared CPUs / 4 GB RAM')
    d.boundary(425,470,1510,285,'APPLICATION PROCESSES · UID 1000', '#e8f0f7','#9eafc1',True)
    d.boundary(425,805,1510,285,'PERSISTENT /data VOLUME · encrypted 10 GB', '#f5eff9','#b5a0c6')
    d.node(45,205,280,150,'EXTERNAL SOURCE','Organizer S3',['Read-only source CSVs','Same source as Docker'],'external')
    d.node(435,205,470,150,'LOCAL · NOT A FLY DAEMON','DuckDB + Docker capture',['Build/publish snapshots; capture approved config','Allowlisted data + consistent SQLite backups'],'batch',size='small')
    d.node(1110,205,805,150,'ONE-TIME PRIVATE MIGRATION','Checksum-verified import → /data',['Gold + silver masters; config, keys, MCP deps; bank continuity records','Bronze/old builds stay local. Imported UI sessions and chats start empty.'],'batch')
    d.node(45,525,280,190,'REMOTE USER','Browser / Savia',['flujo-factored-2026',' .fly.dev · HTTPS:443','UI assets + /api/*'],'external')
    d.node(435,525,280,190,'PUBLIC INGRESS','Gateway · :8080',['Outer demo login gate','Secure / HttpOnly cookie','Proxy only to Savia'],'service')
    d.node(795,525,300,190,'LOOPBACK · :8082','Savia API',['Inner demo/profile login','Session → customer','Signs chat assertion'],'service')
    d.node(1175,525,330,190,'LOOPBACK · :4200','FLUJO worker',['Verifies execution + user','Pins graph / run authority','Sandbox :4201 is private'],'service')
    d.node(1590,525,325,190,'STDIO · NO PUBLIC PORT','Banking MCP',['Read-only owned rows','Masked banking facts','Optional S3 verification'],'data')
    d.node(2100,350,260,175,'EXTERNAL COMPUTE','Model provider',['Codex / configured LLM','Prompt + minimized facts','Reply returns same path'],'external',size='small')
    d.node(2100,605,260,175,'SAME SOURCE S3','Optional recheck',['Only with verify_source','Pinned ETag HEAD / GET','Server credentials only'],'external',size='small')
    d.node(450,855,405,210,'DATASET · READ-ONLY TO APPS','/data/banking-data',['Alias: /banking-data','CURRENT + manifests','Silver masters + current gold','Synthetic fixture also retained'],'data')
    d.node(895,855,300,200,'SAVIA · READ / WRITE','/data/frontend-state',['Login sessions','Public chat transcript','Revocation retry queue'],'state')
    d.node(1235,855,330,210,'FLUJO · READ / WRITE','/data/flujo',['Flow/model/MCP config','Encrypted credentials','New conversations','Bank authority owner ledger'],'state')
    d.node(1605,855,305,200,'MCP · READ / WRITE','/data/banking-state',['SQLite bank ledger','Opaque selection handles','Also: banking-demo-state'],'state')
    d.arrow([(325,275),(435,275)],'batch',dashed=True)
    d.arrow([(905,275),(1110,275)],'batch',dashed=True)
    d.label(1007,258,'package','batch')
    d.arrow([(1885,355),(2015,355),(2015,1125),(650,1125),(650,1065)],'batch',dashed=True)
    d.label(1380,1118,'First import; later releases reuse /data','batch')
    # A read-only data bus feeds both server readers. No shared S3 API is exposed.
    d.arrow([(450,958),(410,958),(410,450),(1760,450),(1760,525)],'data')
    d.arrow([(945,450),(945,525)],'data')
    d.label(760,463,'Owned Parquet rows → DuckDB','data')
    d.arrow([(325,620),(435,620)],two=True)
    d.label(380,571,['HTTPS:443','Fly edge TLS'])
    d.arrow([(715,620),(795,620)],two=True)
    d.label(755,591,'proxy')
    d.arrow([(1095,620),(1175,620)],two=True)
    d.label(1135,571,['HTTP','signed user'])
    d.arrow([(1505,620),(1590,620)],two=True)
    d.label(1547,591,'stdio')
    d.arrow([(1340,525),(1340,495),(2045,495),(2045,425),(2100,425)],two=True)
    d.label(1890,487,'HTTPS / LLM')
    d.arrow([(1915,680),(2100,680)],'data',two=True,dashed=True)
    d.label(2007,646,['Bounded S3','verification'],'data')
    for topx, endx in [(945,1045),(1335,1400),(1755,1755)]:
        d.arrow([(topx,715),(topx,780),(endx,780),(endx,855)],'state',two=True)
        d.label(endx,798,'read / write','state')
    d.text(435,1148,'BOOTSTRAP · /data/private → protected /run files; policy hash checked; dataset sealed RO; services drop to UID 1000.','small')
    d.text(45,174,'DATA ORIGIN','kicker')
    d.text(2100,174,'OUTBOUND ONLY','kicker')
    d.text(45,1108,'RELEASE STATUS','kicker')
    d.text(45,1138,'Adapter repair recorded;', 'small')
    d.text(45,1166,'live acceptance pending*', 'small')
    d.legend('* Recorded Fly release: adapter repair deployed; inquiry + revocation acceptance pending. Configured topology · 30 Sep 2026.')
    return d.finish()


NOTES = '''# Docker and Fly deployment landscapes

Reviewed 30 September 2026. These are configuration diagrams, with data-plane
paths separated from requests, batch migration and persistent state. No customer
rows, private identities, bucket names, tokens or signing keys are included.

## Docker

1. The customer opens `http://localhost:43800`. The published port is bound to
   `127.0.0.1` and forwards to Savia's container port 8080. The browser runs the
   static frontend and calls Savia `/api/*`; it never opens Parquet or S3 itself.
2. Savia's FastAPI server authenticates the demo profile, binds the session to an
   approved customer, and uses DuckDB to query the mounted snapshot. Its joins
   require customer/product ownership and valid transaction ownership.
3. For chat, Savia calls `http://flujo:4200/v1/chat/completions` over the private
   Docker network, with an execution bearer and a short-lived Ed25519 signed user
   assertion. The logout path calls `/v1/banking/session/revoke`. Frontend signers
   and upstream credentials stay in the server. The configured worker verifies
   admission, binds the owner and pins the approved graph.
4. The restricted inquiry run calls the banking MCP as a Python **stdio child**,
   with run-bound customer authority. MCP checks customer and product ownership
   again and returns masked facts and opaque selection handles. Its ordinary
   read path is the shared read-only Parquet snapshot, not a live S3 scan.
5. When `verify_source` is requested for a selected transaction, MCP makes
   bounded, ETag-pinned S3 HEAD/GET reads of the relevant source objects. This
   verification does not refresh or publish a new snapshot and does not write S3.
6. Savia, FLUJO and MCP each have separate writable state volumes. The shared
   dataset and private config/signers are read-only host binds. FLUJO :4200 and
   its :4201 sandbox have no published host ports.
7. Other local access paths: the operator opens `http://localhost:43420` through
   the UI proxy; Slack reaches a separate Socket Mode gateway that shares the
   worker's network namespace and uses `127.0.0.1:4200`. This Slack path has its
   own service credentials and is not a substitute for customer banking identity.
   The synthetic-only preview at `localhost:43801` is a separate deployment and
   is outside this real-snapshot diagram.

**Docker status:** the deployment README records that the captured source
worker's compiled banking adapter was missing, so its customer banking chat and
revocation could fail authentication. The arrows describe configured paths;
they do not assert that this image completes them successfully.

## Fly

1. The user opens `https://flujo-factored-2026.fly.dev`. Fly edge terminates
   HTTPS and forwards to gateway 8080, the only public service listener. The
   gateway's outer demo login issues a Secure, HttpOnly, SameSite=Strict cookie.
   The inner Savia demo/profile login remains required as configured.
2. The gateway proxies customer traffic only to Savia at `127.0.0.1:8082`.
   Savia serves the frontend assets and APIs, reads the same logical snapshot,
   and sends signed customer chat to FLUJO at `127.0.0.1:4200`. The worker's
   :4201 sandbox and the stdio banking MCP remain private.
3. Gateway, Savia and FLUJO run in the **same Machine**, supervised together.
   Runtime services run as UID 1000. This is process separation and loopback
   networking, rather than separate Fly apps or a 6PN service network.
4. The mounted encrypted 10 GB volume `/data` holds the published dataset,
   frontend state, FLUJO configuration and new conversations, banking authority
   state, and real/synthetic MCP state. `/banking-data` aliases
   `/data/banking-data`; `/banking-state` aliases `/data/banking-state`.
5. Initial migration packages current gold, silver customer/product masters,
   manifests, approved configuration, signers, runtime dependencies and
   consistent bank SQLite backups. Bronze and historical builds stay local.
   Imported conversations/browser sessions start empty; new state then persists.
6. Root bootstrap validates the migration marker and approved policy hash,
   publishes private runtime config into protected `/run` files, seals the
   dataset read-only to application services, and drops runtime services to
   UID 1000. Private migration data and credentials do not enter the image.
7. S3 verification and the external model-provider calls are outbound paths.
   The provider receives the inquiry and minimized facts, not AWS credentials
   or a direct dataset API. All bank tools are read-only and bank actions remain
   disabled. No recurring Fly ETL or automatic dataset refresh is configured.
8. The local Slack deployment continues independently after the Fly migration.
   Fly's health endpoint probes Savia dataset readiness and authenticated worker
   readiness; a healthy probe alone does not verify a complete customer inquiry.

**Fly status:** the deployment README records the corrected banking-adapter
image as deployed, with customer inquiry, logout revocation and exact-session
ledger acceptance still pending. This documentation task did not run those live
checks or change either deployment. The first uncorrected migration image had
the same adapter omission as the captured Docker source.

## Scope and sources

Docker means the existing local multi-container deployment. The file
`deploy/fly/Dockerfile` is additionally a **local combined-image build option for
Fly**; it is not the topology of the running local Docker stack. Fly's canonical
remote build uses `Dockerfile.remote`, with `Dockerfile.bank-enabled` adding the
banking adapter repair.

The S3 origin is drawn twice in each SVG to keep arrows legible: left for offline
ingestion, right for an optional runtime source check. It is the same source.
DuckDB runs inside the pipeline and each serving reader; it is not a network
database. Persistence arrows cover application state, not writes to source data.

Evidence:

- `pipeline/README.md`, `pipeline/common.py`, `pipeline/lookup.py`: pipeline,
  snapshot publication and ownership filtering.
- `deploy/fly/fly.toml`, `runtime.mjs`, `gateway.mjs`, `capture-docker.mjs`,
  `README.md`: Fly boundaries, loopback ports, migrations, persistence and status.
- Running Docker port/network/mount metadata for
  `hackathon-banking-frontend-1` and `flujo-slack-flujo-1`.
- Frontend source in the running image: `server/app.py`, `server/repository.py`,
  `server/chat.py`; banking image source: `banking_mcp/server.py`,
  `banking_mcp/service.py`, `banking_mcp/repository.py`.
- Local frontend Compose files in the `banking-frontend` worktree and the sibling
  `flujo-slack-bot/compose.yaml`, `src/ui.js`, `README.md`.
- Only allowlisted non-secret fields were inspected from private runtime configs.
  Planning documents with earlier direct-S3 proposals were not treated as the
  deployed serving topology.

## Files

- `docker-landscape.svg`, `fly-landscape.svg`: editable vector diagrams.
- `docker-landscape.png`, `fly-landscape.png`: rendered image previews.
- `deployment-landscapes.pdf`: two landscape vector pages for sharing.
- `deployment-landscapes.html`: self-contained viewer, zoom and descriptions.
- `build-landscapes.py`: regenerates SVGs, viewer and these notes. PNG/PDF exports
  use a local browser render of the SVGs.
'''


def historical_viewer(docker_svg, fly_svg):
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Docker &amp; Fly · deployment landscapes</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#e9eff2;color:#18323d;font:16px Arial,Helvetica,sans-serif}
header{position:sticky;top:0;z-index:4;display:flex;align-items:center;gap:18px;padding:18px 24px;background:#fff;border-bottom:1px solid #c8d5db;flex-wrap:wrap}
h1{font-size:20px;margin:0 15px 0 0}button,a{font:inherit}button{padding:9px 16px;border:1px solid #a8b9c3;border-radius:8px;background:#fff;color:#18323d;cursor:pointer}button[aria-pressed=true]{background:#18323d;color:#fff;border-color:#18323d}
nav{display:flex;gap:8px}a{color:#2869b2;text-underline-offset:3px}.spacer{flex:1}.diagram{overflow:auto;background:#f7fafb;border-bottom:1px solid #c8d5db}.diagram svg{display:block;width:100%;height:auto;min-width:1100px}body.zoom .diagram svg{width:2400px;max-width:none;min-width:2400px}
article{max-width:1250px;margin:24px auto 50px;background:#fff;border:1px solid #c8d5db;border-radius:12px;padding:24px 30px;line-height:1.6}h2{font-size:22px;margin:0 0 12px}.lead{font-size:18px}ol{padding-left:25px}li{margin:10px 0}.status{padding:14px 18px;background:#fff8e8;border:1px solid #dbc599;border-radius:8px}section[hidden]{display:none}.downloads{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px}code{background:#f0f4f6;padding:2px 4px;border-radius:4px}
@media print{header,article{display:none}section[hidden]{display:block}section{break-after:page}.diagram{border:0;overflow:visible}.diagram svg{width:100%;min-width:0!important}body{background:white}}
</style></head><body><header><h1>Deployment landscapes</h1><nav aria-label="Deployment"><button id="docker-tab" aria-pressed="true" onclick="select('docker')">Docker · local</button><button id="fly-tab" aria-pressed="false" onclick="select('fly')">Fly · hosted</button></nav><button id="zoom" aria-pressed="false" onclick="zoom()">Actual size / pan</button><span class="spacer"></span><a href="deployment-landscapes.pdf" download>Download both as PDF</a><a href="landscape-notes.md">Full source notes</a></header>
<section id="docker"><div class="diagram">''' + docker_svg + '''</div><article><h2>Docker: separate containers, shared read-only snapshot</h2><div class="downloads"><a href="docker-landscape.svg" download>Editable SVG</a><a href="docker-landscape.png" download>PNG image</a></div><p class="lead">The browser talks to Savia. Savia reads owned snapshot rows for the screens and sends signed customer chat to the private FLUJO worker. The worker calls the banking MCP; the MCP reads the same snapshot and can verify a selected transaction against S3.</p><ol><li><b>Data origin:</b> organizer S3 CSVs → offline DuckDB bronze/silver/gold pipeline → published <code>data/CURRENT</code> snapshot. Rejected rows go to quarantine. This is a batch operation, not a query from the browser.</li><li><b>User connection:</b> <code>localhost:43800</code> → Savia container port 8080. The browser receives JS/CSS and scoped JSON; server credentials, customer mapping and Parquet remain private.</li><li><b>Frontend access:</b> FastAPI + DuckDB read <code>/banking-data</code>. Its customer/product ownership checks scope overview and transaction screens to the login session.</li><li><b>Backend access:</b> Savia signs the user assertion and calls <code>http://flujo:4200/v1/chat/completions</code>. The configured FLUJO adapter pins customer and graph authority. A restricted inquiry run calls a customer-bound Python MCP over stdio; it returns masked facts and handles.</li><li><b>External flows:</b> the model provider receives the inquiry and minimized tool facts over HTTPS. Optional <code>verify_source</code> performs bounded, ETag-pinned S3 HEAD/GET reads. S3 is not written, and neither the UI nor the model receives AWS credentials.</li><li><b>Persistence and other users:</b> frontend, worker and MCP state live in separate volumes. The operator UI uses <code>localhost:43420</code> → UI proxy → worker. Slack uses a separate Socket Mode gateway → worker loopback. The independent synthetic-only preview on 43801 is outside this diagram.</li></ol><p class="status"><b>Recorded limitation:</b> the captured Docker worker image lacks the compiled banking execution adapter; customer chat and revocation can fail authentication. Arrows show the configured architecture, not a successful acceptance test.</p><p>The S3 source is repeated on the right for a legible optional verification path. Docker here is the existing multi-container stack; <code>deploy/fly/Dockerfile</code> is also available to build a combined Fly image locally.</p></article></section>
<section id="fly" hidden><div class="diagram">''' + fly_svg + '''</div><article><h2>Fly: one public gateway, one Machine, one persistent volume</h2><div class="downloads"><a href="fly-landscape.svg" download>Editable SVG</a><a href="fly-landscape.png" download>PNG image</a></div><p class="lead">The public HTTPS gateway reaches Savia only. Savia, FLUJO and banking MCP communicate privately inside one Fly Machine. The snapshot and writable state live on the persistent <code>/data</code> volume.</p><ol><li><b>Data arrival:</b> the initial private migration imports current gold, silver customer/product masters, manifests, approved configuration, keys, MCP dependencies and consistent bank SQLite backups. Bronze and old builds stay local. Imported sessions and chat history start empty.</li><li><b>User connection:</b> <code>https://flujo-factored-2026.fly.dev</code> → Fly edge TLS → gateway 8080 → Savia 8082. The gateway adds an outer login gate with a Secure, HttpOnly cookie; the inner demo/profile login still applies.</li><li><b>Frontend access:</b> Savia serves static frontend assets and <code>/api/*</code>. DuckDB reads owned rows through <code>/banking-data</code>, an alias for <code>/data/banking-data</code>. The browser never reads the dataset directly.</li><li><b>Backend access:</b> signed chat goes to <code>127.0.0.1:4200</code>; FLUJO calls banking MCP over stdio with customer/run authority. Savia 8082, worker 4200 and sandbox 4201 are loopback services. Only gateway 8080 is the public service listener.</li><li><b>Boundaries:</b> root bootstrap validates the approved policy hash, creates protected runtime files, seals the dataset read-only, then runs services as UID 1000. Gateway, Savia and worker are supervised processes in one Machine; they are not separate Fly apps.</li><li><b>Persistence:</b> the encrypted 10 GB <code>/data</code> volume keeps dataset, frontend sessions/chat, worker config/credentials/new conversations, authority records and MCP ledgers. Later image deployments reuse it. No recurring Fly ETL is configured.</li><li><b>Outbound services:</b> Codex/the configured model receives the inquiry and minimized facts. Banking MCP can perform optional bounded S3 verification using private runtime credentials. Bank actions remain disabled. The local Slack deployment continues independently.</li></ol><p class="status"><b>Recorded release status:</b> the banking-adapter repair image is recorded as deployed. Customer inquiry, logout revocation and exact-session ledger acceptance remain pending in the deployment README. The health endpoint checks worker/data readiness, not full customer acceptance.</p><p>Source: repository configuration and inspected local Docker metadata as of 30 September 2026. This documentation task does not change either deployment or independently verify live Fly behavior.</p></article></section>
<script>function select(id){for(const item of ['docker','fly']){document.getElementById(item).hidden=item!==id;document.getElementById(item+'-tab').setAttribute('aria-pressed',String(item===id))}location.hash=id}function zoom(){const active=document.body.classList.toggle('zoom');document.getElementById('zoom').setAttribute('aria-pressed',String(active));document.getElementById('zoom').textContent=active?'Fit to window':'Actual size / pan'}if(location.hash==='#fly')select('fly');</script></body></html>'''


def scoped_svg(svg, prefix):
    # SVG identifiers share the HTML document namespace, including hidden tabs.
    for identifier in ['title', 'desc', *COLORS]:
        svg = svg.replace(f'id="{identifier}"', f'id="{prefix}-{identifier}"')
        svg = svg.replace(f'url(#{identifier})', f'url(#{prefix}-{identifier})')
    return svg.replace('aria-labelledby="title desc"', f'aria-labelledby="{prefix}-title {prefix}-desc"')


def viewer(docker_svg, fly_svg, current_svg):
    html = historical_viewer(scoped_svg(docker_svg, 'docker'), scoped_svg(fly_svg, 'fly'))
    html = html.replace('Docker &amp; Fly · deployment landscapes', 'Savia · technical product architecture')
    html = html.replace('</style>', DOCUMENT_CSS + '\n@media print{article.technical{display:block!important}}\n</style>', 1)
    html = html.replace('<h1>Deployment landscapes</h1>', '<h1>System landscape</h1>')
    html = html.replace('<nav aria-label="Deployment">', '<nav aria-label="Deployment"><button id="system-tab" aria-pressed="true" onclick="select(\'system\')">Savia · architecture</button>')
    html = html.replace('id="docker-tab" aria-pressed="true"', 'id="docker-tab" aria-pressed="false"')
    html = html.replace('Docker · local</button>', 'Docker · Sep 30</button>').replace('Fly · hosted</button>', 'Fly · Sep 30</button>')
    html = html.replace('<a href="deployment-landscapes.pdf" download>Download both as PDF</a>', '<a href="system-landscape.pdf" download>Technical PDF</a><a href="deployment-landscapes.pdf" download>Sep 30 PDF</a>')
    html = html.replace('<a href="landscape-notes.md">Full source notes</a>', '<a href="system-landscape.md">Document source</a>')
    html = html.replace('<section id="docker">', system_section(scoped_svg(current_svg, 'system'))+'<section id="docker" hidden>')
    html = html.replace("['docker','fly']", "['system','docker','fly']")
    html = html.replace("if(location.hash==='#fly')select('fly');", "function selectHash(){const id=location.hash.slice(1);select(['system','docker','fly'].includes(id)?id:'system')}window.addEventListener('hashchange',selectHash);selectHash();")
    return html


if __name__ == '__main__':
    docker_svg, fly_svg, current_svg = docker(), fly(), system_svg(Diagram)
    for name, content in [('docker-landscape.svg',docker_svg), ('fly-landscape.svg',fly_svg), ('system-landscape.svg',current_svg), ('system-landscape.html',standalone(current_svg)), ('deployment-landscapes.html',viewer(docker_svg,fly_svg,current_svg)), ('landscape-notes.md',NOTES)]:
        (ROOT/name).write_text(content,encoding='utf-8')
    print(json.dumps({'written':['docker-landscape.svg','fly-landscape.svg','system-landscape.svg','system-landscape.html','deployment-landscapes.html','landscape-notes.md']}))
