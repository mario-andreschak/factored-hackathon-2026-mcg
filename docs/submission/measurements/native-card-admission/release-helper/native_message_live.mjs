/** Future two-message admission only. --describe makes no browser/network call. */
import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {performance} from 'node:perf_hooks';
import {validateBinding,privateChild,sha,ROOT} from './binding_gate.mjs';
import {validateNativeEvents,PHRASES,admitPost} from './event_gate.mjs';
const PACKAGE='[private-local-path]';
const describe={schema:'savia-card-admission-native-message-live/v1',preparedOnly:true,maximumDurationMs:120000,
  maximumProviderEligibleRequests:2,cases:['es/mexico','pt/colombia'],phrases:PHRASES,
  endpoint:'/api/voice/turn',inputKind:'message',voiceUIOff:true,asrQualified:false,microphoneQualified:false,
  freshUIPlaybackQualified:false,playedACKRequests:0,resultSpeechRequests:0,chatDispatchRequests:0,
  cardWrites:0,authentication:'Normal browser gateway/profile/code forms; unrecorded, storage in memory',
  output:'Private NDJSON and mechanical receipt. No publication; no credential/config/storage output.',
  observedDelegateMeaning:'Source-bound evidence of admitted tool availability and real provider consultar_savia choice; exact input preserved',
  retainedEvidence:'Dated c44 native_exact host-result speech and real UI /played ACK proof; no new positive UI claim'};
const stable=x=>Array.isArray(x)?x.map(stable):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,stable(x[k])])):x;
const hashObject=x=>sha(JSON.stringify(stable(x)));
function blocked(result,reference){return result?.state==='card_block_verified'&&result.product_reference===reference&&result.simulated===true&&result.real_bank_action===false&&result.receipt?.schema==='savia-simulated-card-block/v1'&&result.receipt.status==='blocked'&&result.receipt.simulated===true&&result.receipt.real_bank_action===false;}
async function execute(bindingPath){
  assert(bindingPath,'New private binding required');const {cfg}=await validateBinding(bindingPath);
  assert.equal(sha(await fs.readFile(new URL(import.meta.url))),cfg.native_harness_sha256);
  const out=privateChild(path.join(ROOT,'native-private',new Date().toISOString().replace(/[:.]/g,'-')));
  await fs.mkdir(path.dirname(out),{recursive:true});await fs.mkdir(out,{recursive:false});
  const require=createRequire(PACKAGE),pw=require('playwright');
  const started=performance.now(),elapsed=()=>Math.round(performance.now()-started);
  const report={...describe,preparedOnly:false,startedAt:new Date().toISOString(),
    source:cfg.runtime.git_head,imageDigest:cfg.runtime.image_digest,browserSource:cfg.runtime.browser_source,
    descriptorSha256:cfg.expected_runtime_sha256,helperSha256:cfg.native_harness_sha256,
    observedProviderEligibleRequests:0,observedCardStatusRequests:0,cases:[],passed:false};
  let browser,fatal=null;const fail=message=>{fatal ||= message;};
  const ensure=()=>{if(fatal)throw Error(fatal);if(elapsed()>118000)throw Error('Total native probe budget expired.');};
  const timer=setTimeout(()=>{fail('120-second native message bound exceeded.');void browser?.close().catch(()=>{});},120000);
  try{
    browser=await pw.chromium.launch({headless:true,channel:'msedge',timeout:20000});
    for(const spec of cfg.cases){
      ensure();const phrase=PHRASES[spec.language],copy=spec.language==='pt'?{group:'Escolha um perfil de demonstração',login:'Entrar no meu banco'}:{group:'Elige un perfil de demostración',login:'Entrar a mi banca'};
      let state;const entry=await browser.newContext({viewport:{width:1360,height:900},locale:'es-CO'});
      try{
        let logins=0,gates=0;
        await entry.route('**/*',async route=>{
          const request=route.request(),url=new URL(request.url());
          if(url.origin!==cfg.base_url)return route.abort();
          if(['GET','HEAD'].includes(request.method()))return route.continue();
          if(request.method()==='POST'&&url.pathname==='/_rc/enter'&&++gates===1)return route.continue();
          if(request.method()==='POST'&&url.pathname==='/api/auth/login'&&++logins===1)return route.continue();
          fail('Unexpected authentication write');return route.abort();
        });
        const page=await entry.newPage();page.setDefaultTimeout(30000);
        const profilesWait=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/profiles',{timeout:30000});
        await page.goto(cfg.base_url,{waitUntil:'domcontentloaded'});
        if(await page.getByLabel(cfg.gateway.label,{exact:true}).count()){
          await page.getByLabel(cfg.gateway.label,{exact:true}).fill(cfg.gateway.code);
          await page.getByRole('button',{name:cfg.gateway.button,exact:true}).click();
        }
        const profiles=await (await profilesWait).json(),profile=profiles.profiles?.find(p=>p.id===spec.profile);assert(profile,'Approved fictional profile absent');
        await page.locator('.login-language select').selectOption(spec.language);
        await page.getByRole('group',{name:copy.group,exact:true}).getByRole('button').filter({hasText:profile.alias}).click();
        await page.locator('#login-code').fill(cfg.code);
        const loginWait=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/login'&&r.request().method()==='POST',{timeout:30000});
        await page.getByRole('button',{name:copy.login,exact:true}).click();assert.equal((await loginWait).status(),200);
        state=await entry.storageState(); // In memory only, never persisted.
      }finally{await entry.close();}
      const item={language:spec.language,fictionalProfile:spec.profile,inputMessage:phrase,servedAssets:[],passed:false};report.cases.push(item);
      const context=await browser.newContext({viewport:{width:1360,height:900},locale:'es-CO',storageState:state});state=null;
      const assetChecks=[],budget={native:0,status:0};
      try{
        await context.route('**/*',async route=>{
          const request=route.request(),url=new URL(request.url());
          if(url.origin!==cfg.base_url){fail('Unexpected external request');return route.abort();}
          if(url.pathname==='/api/assistant/voice-update'){return route.abort();}
          if(url.pathname.startsWith('/api/analytics')){fail('Analytics outside bounded probe');return route.abort();}
          if(['GET','HEAD'].includes(request.method()))return route.continue();
          let body;try{body=request.postDataJSON();}catch{}
          const kind=request.method()==='POST'?admitPost(url.pathname,body,spec.language,budget):null;
          let permitted=kind!==null;
          if(kind==='status')report.observedCardStatusRequests++;
          if(kind==='native')permitted=++report.observedProviderEligibleRequests<=2;
          if(!permitted){fail('Unexpected write, result/audio input, chat/ACK/card action or request budget exceeded');await route.abort();void browser.close().catch(()=>{});return;}
          await route.continue();
        });
        const page=await context.newPage();page.setDefaultTimeout(10000);
        page.on('response',response=>{
          const name=new URL(response.url()).pathname;
          if(name.startsWith('/assets/'))assetChecks.push((async()=>{
            const observed={path:name.slice(1),status:response.status(),sha256:sha(await response.body())};
            assert.equal(observed.status,200);assert.equal(cfg.runtime.served_ui[observed.path],observed.sha256);item.servedAssets.push(observed);
          })().catch(()=>fail('Actual browser asset differs from retained c44 bytes')));
        });
        await page.goto(cfg.base_url,{waitUntil:'networkidle'});ensure();
        assert(await page.locator('nav').count()>0&&await page.locator('#login-code, .login-language').count()===0,'Authenticated product page required');
        assert.equal(await page.locator('[data-phase="listening"],[data-phase="speaking"]').count(),0,'Voice UI must remain off');
        const overview=await page.evaluate(async()=>{const r=await fetch('/api/overview',{credentials:'same-origin'});return {status:r.status,body:await r.json()};});assert.equal(overview.status,200);
        const card=overview.body.products?.find(p=>p.status==='Active'&&/tarjeta|cart[aã]o/i.test(p.type)&&p.card_protection_status==='blocked');assert(card,'Existing owned blocked card required; no new block authorized');
        const readStatus=()=>page.evaluate(async({reference,language})=>{const r=await fetch('/api/cards/block',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_reference:reference,operation:'status',language})});return {status:r.status,body:await r.json()};},{reference:card.reference,language:spec.language});
        const before=await readStatus();assert.equal(before.status,200);assert(blocked(before.body,card.reference));
        const beforeHash=hashObject(before.body.receipt);
        ensure();const native=await page.evaluate(async({message,language})=>{
          const r=await fetch('/api/voice/turn',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,language,fresh:true}),signal:AbortSignal.timeout(45000)});
          const reader=r.body.getReader(),decoder=new TextDecoder();let text='',bytes=0;
          while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.length;if(bytes>16000000){await reader.cancel();throw Error('Bounded native NDJSON exceeded');}text+=decoder.decode(value,{stream:true});}
          text+=decoder.decode();return {status:r.status,contentType:r.headers.get('content-type'),text};
        },{message:phrase,language:spec.language});
        assert.equal(native.status,200);assert(native.contentType?.includes('application/x-ndjson'));assert(native.text.endsWith('\n'),'Normal terminal newline required');
        const events=native.text.trim().split('\n').map(line=>JSON.parse(line));
        await fs.writeFile(path.join(out,spec.language+'.ndjson'),native.text,{flag:'wx'});
        item.ndjsonSha256=sha(native.text);item.nativeAdmission=validateNativeEvents(events,spec.language);
        const after=await readStatus();assert.equal(after.status,200);assert(blocked(after.body,card.reference));assert.equal(hashObject(after.body.receipt),beforeHash);
        item.existingCardProtection={beforeVerified:true,afterVerified:true,savedReceiptSha256:beforeHash,savedReceiptUnchanged:true,statusReads:2,newCardWrites:0};
        await Promise.allSettled(assetChecks);ensure();assert(item.servedAssets.some(a=>/^assets\/index-.*\.js$/.test(a.path)),'Actual retained c44 JS must be observed');
        item.passed=true;
      }catch(error){item.failure=error.message;fail(error.message);}
      finally{await context.close().catch(()=>{});}
      if(fatal)break;
    }
    await validateBinding(bindingPath);report.passed=!fatal&&report.cases.length===2&&report.cases.every(c=>c.passed)&&report.observedProviderEligibleRequests===2&&report.observedCardStatusRequests===4;
  }catch(error){fail(error.message);}
  finally{
    await browser?.close().catch(()=>{});clearTimeout(timer);report.failure=fatal;report.finishedAt=new Date().toISOString();report.durationMs=elapsed();
    await fs.writeFile(path.join(out,'receipt-private.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});
    console.log(JSON.stringify({passed:report.passed,caseCount:report.cases.length,providerEligibleRequests:report.observedProviderEligibleRequests,cardWrites:0,playedACKRequests:0,receiptSha256:sha(JSON.stringify(report,null,2)+'\n'),failure:fatal}));
    if(!report.passed)process.exitCode=1;
  }
}
const [mode,bindingPath]=process.argv.slice(2);
if(mode==='--describe')console.log(JSON.stringify(describe,null,2));
else if(mode==='--execute')await execute(bindingPath);
else throw Error('Only --describe or explicitly root-approved --execute PRIVATE_BINDING is permitted.');
