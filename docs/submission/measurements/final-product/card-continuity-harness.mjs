import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
const [revision, image] = process.argv.slice(2);
assert.match(revision, /^[0-9a-f]{40}$/);
assert.match(image, /^registry\.fly\.io\/savia-rc-2026@sha256:[0-9a-f]{64}$/);
const base='https://savia-rc-2026.fly.dev';
const repo='C:/Users/Moe/.codex/worktrees/savia-score-90/factored-hackathon-2026';
const prior=JSON.parse(await fs.readFile(path.join(repo,'docs/submission/measurements/native-canonical-live/receipt.json'),'utf8'));
const stable=value=>Array.isArray(value)?value.map(stable):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(k=>[k,stable(value[k])])):value;
const hash=value=>createHash('sha256').update(JSON.stringify(stable(value))).digest('hex');
const observed=[];
let httpChecks=0;
for(const entry of prior.cases){
 const cookies=new Map();
 async function request(route, options={}){
  assert(['/','/_rc/enter','/api/auth/login','/api/overview','/api/cards/block'].includes(route));
  if(route==='/api/cards/block')assert.equal(JSON.parse(options.body).operation,'status');
  const response=await fetch(base+route,{redirect:'manual',...options,
   headers:{Origin:base,...options.headers,Cookie:[...cookies].map(([k,v])=>k+'='+v).join('; ')},signal:AbortSignal.timeout(30000)});
  for(const line of response.headers.getSetCookie()){const pair=line.split(';')[0];const index=pair.indexOf('=');cookies.set(pair.slice(0,index),pair.slice(index+1));}
  httpChecks++;
  return response;
 }
 assert.equal((await request('/')).status,200);
 assert.equal((await request('/_rc/enter',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'code=SAVIA-2026'})).status,303);
 assert.equal((await request('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({profile:entry.fictionalProfile,code:'SAVIA-2026'})})).status,200);
 const overview=await request('/api/overview');assert.equal(overview.status,200);
 const products=(await overview.json()).products;
 const card=products.find(p=>p.status==='Active'&&/tarjeta|cart[aã]o/i.test(p.type)&&p.card_protection_status==='blocked');assert(card);
 const hashes=[];
 for(let i=0;i<2;i++){
  const response=await request('/api/cards/block',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_reference:card.reference,operation:'status',language:entry.language})});
  assert.equal(response.status,200);
  const result=await response.json();
  assert.equal(result.state,'card_block_verified');assert.equal(result.product_reference,card.reference);
  assert.equal(result.simulated,true);assert.equal(result.real_bank_action,false);
  assert.equal(result.receipt.schema,'savia-simulated-card-block/v1');assert.equal(result.receipt.status,'blocked');
  hashes.push(hash(result.receipt));
 }
 assert.equal(hashes[0],hashes[1]);assert.equal(hashes[0],entry.existingCardProtection.initialSavedReceiptSha256);
 observed.push({language:entry.language,fictionalProfile:entry.fictionalProfile,owned_status_verified:true,
  saved_receipt_sha256:hashes[0],matches_dated_predecessor_receipt:true,independent_reads:2});
}
const out='C:/Users/Moe/.codex/tmp/savia-final-runtime-'+revision.slice(0,12)+'/card-status-continuity.json';
const report={schema:'savia-final-card-status-continuity/v1',at_utc:new Date().toISOString(),
 application_source:revision,image,passed:true,http_checks:httpChecks,cases:observed,
 new_card_prepare_confirm_cancel_requests:0,provider_calls:0,
 scope:'Read-only owned-card status and unchanged saved-receipt verification after image promotion. New authentication sessions only; no new card block or voice acceptance.'};
await fs.writeFile(out,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({passed:true,http_checks:httpChecks,qualified_cases:observed.length,new_card_writes:0,provider_calls:0,receipt:out}));
