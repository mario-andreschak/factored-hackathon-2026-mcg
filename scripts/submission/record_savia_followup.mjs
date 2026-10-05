/** One original-case normal-clock follow-up. No POST, login, voice or provider calls. */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';

const scope={schema:'savia-original-case-normal-clock-followup/v1',apiWrites:0,modelRequests:0,
 newCases:0,newWorkers:0,voiceTurns:0,historyReset:0,clockInjection:false,
 input:'actual accepted new fleet customer capture, same saved legitimate SID and inquiry',
 observation:'after actual stored due time, ordinary voice-off UI GET-only follow-up; max35min after completion',
 executionHeldUntilAcceptedNewCapture:true};
const [mode,capturePath,bindingPath,outputPath]=process.argv.slice(2);
if(mode==='--describe')console.log(JSON.stringify(scope,null,2));
else if(mode==='--execute')await execute();
else throw Error('Use --describe, or --execute PRIVATE_ACCEPTED_CAPTURE PRIVATE_NEW_BINDING NEW_PRIVATE_DIR.');

async function execute(){
 const capture=path.resolve(capturePath),cfg=JSON.parse(await fs.readFile(bindingPath,'utf8'));
 const prior=JSON.parse(await fs.readFile(path.join(capture,'receipt.json'),'utf8'));
 const original=prior.completedInquiry,origin=new URL(cfg.base_url).origin;
 if(cfg.root_go!==true||cfg.followup_root_go!==true||cfg.fleet_customer_run!==true||
    !prior.completed||!prior.contextRestored||prior.schema!=='savia-fleet-native-customer-journey/v1'||
    prior.sourceGitHead!==cfg.runtime?.git_head||prior.imageDigest!==cfg.runtime?.image_digest||
    prior.baseUrl!==origin||cfg.base_url!==origin||!origin.startsWith('https://')||
    original?.execution?.review_status!=='verified'||original.bank_authority!==false||
    !/^i_[a-f0-9]{32}$/.test(original.id||'')||!Number.isInteger(original.next_check_at))
  throw Error('Explicit follow-up GO and accepted exact new original capture required.');
 const due=original.next_check_at*1000,deadline=due+300000;
 const completedEvent=original.events.find(x=>x.kind==='team_completed');
 if(!completedEvent||Math.abs(original.next_check_at-completedEvent.at-1800)>2)
  throw Error('Actual first half-hour follow-up schedule unavailable.');
 if(Date.now()>deadline)throw Error('Original <=35min observation window expired; do not invent a later run.');
 const out=path.resolve(outputPath);
 if(!out.includes(`${path.sep}private${path.sep}`))throw Error('Initial follow-up artifacts must remain private.');
 await fs.mkdir(out,{recursive:false});
 const receipt={...scope,startedAt:new Date().toISOString(),sourceGitHead:prior.sourceGitHead,
  imageDigest:prior.imageDigest,targetCaseId:original.id,baseUrl:origin,actualDueAt:original.next_check_at,
  originalCompletedAt:completedEvent.at,followupObserved:false,events:[],servedJS:[],apiWrites:[],ownedContextsClosed:false};
 const started=performance.now(),at=()=>Math.round(performance.now()-started);
 let browser,context,page,failure,cases,history,caseReads=0,historyReads=0,deadlineTimer;const tasks=[];
 const fail=message=>{failure??=message;};
 const ensure=()=>{if(failure)throw Error(failure);};
 try{
  let lastProgress=0;
  while(Date.now()<due+2500){
   if(Date.now()-lastProgress>60000){
    console.log(JSON.stringify({phase:'waiting-normal-clock',remainingSeconds:Math.ceil((due-Date.now())/1000),browserOpened:false}));
    lastProgress=Date.now();
   }
   await new Promise(r=>setTimeout(r,Math.min(30000,due+2500-Date.now())));
  }
  const require=createRequire(path.resolve(cfg.playwright_package_json||'frontend/package.json'));
  browser=await require('playwright').chromium.launch({headless:true,channel:cfg.channel||'msedge'});
  deadlineTimer=setTimeout(()=>{fail('Original35min follow-up window expired.');void browser.close();},Math.max(1,deadline-Date.now()));
  const viewport={width:1360,height:900};
  context=await browser.newContext({viewport,locale:'es-CO',timezoneId:'America/Bogota',
   storageState:path.join(capture,'browser-state-private.json'),recordVideo:{dir:out,size:viewport}});
  await context.route('**/api/**',async intercepted=>{
   const request=intercepted.request();
   if(request.method()!=='GET'){
    receipt.apiWrites.push({path:new URL(request.url()).pathname,method:request.method(),atMs:at()});
    fail('Unexpected non-GET application request blocked before forwarding.');
    await intercepted.abort();void browser.close();return;
   }
   await intercepted.continue();
  });
  page=await context.newPage();
  page.on('response',response=>{
   const route=new URL(response.url()).pathname;
   if(route.endsWith('.js'))tasks.push((async()=>{
    try{receipt.servedJS.push({path:route,status:response.status(),sha256:createHash('sha256').update(await response.body()).digest('hex')});}
    catch(error){fail(error.message);}
   })());
   if(!route.startsWith('/api/'))return;
   receipt.events.push({path:route,method:response.request().method(),status:response.status(),atMs:at()});
   tasks.push((async()=>{
    try{
     if(response.status()>=400){fail(`Actual application GET failed: ${route}`);return;}
     if(route==='/api/assistant/cases'){cases=(await response.json()).items||[];caseReads++;}
     else if(route==='/api/chat/history'){history=(await response.json()).messages||[];historyReads++;}
     else if(route==='/api/auth/me')receipt.actualSessionHTTP=response.status();
    }catch(error){receipt.optionalReadErrors??=[];receipt.optionalReadErrors.push({path:route,message:error.message});}
   })());
  });
  await page.goto(origin,{waitUntil:'networkidle'});await Promise.allSettled(tasks);ensure();
  if(receipt.actualSessionHTTP!==200||!receipt.servedJS.some(x=>x.status===200&&/^\/assets\/index-.*\.js$/.test(x.path)&&
    cfg.runtime.served_ui?.[x.path.slice(1)]===x.sha256))throw Error('Original SID or actual served source no longer matches.');
  await page.getByRole('button',{name:'Movimientos',exact:true}).click();
  await page.locator('.transaction-row').filter({hasText:'Nébula Market'}).first().click();
  await page.getByRole('button',{name:'Revisar este cargo',exact:true}).click();
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).waitFor();
  let retained;
  while(Date.now()<=deadline){
   ensure();retained=cases?.find(x=>x.id===original.id);
   if(caseReads>0&&historyReads>0&&retained?.state==='awaiting_customer'&&
      retained.events.some(x=>x.kind==='awaiting_customer'&&x.at>=original.next_check_at&&
       x.id>original.events.at(-1).id))break;
   await new Promise(r=>setTimeout(r,500));
  }
  if(!retained||retained.state!=='awaiting_customer')throw Error('Actual normal-clock follow-up not observed within35min.');
  const event=retained.events.find(x=>x.kind==='awaiting_customer'&&x.at>=original.next_check_at&&x.id>original.events.at(-1).id);
  if(!event||retained.execution?.review_status!=='verified'||retained.bank_authority!==false||
     JSON.stringify(retained.workers)!==JSON.stringify(original.workers)||
     JSON.stringify(history.map(x=>({role:x.role,text:x.text})))!==
     JSON.stringify(prior.restoredServerHistory.map(x=>({role:x.role,text:x.text}))))
   throw Error('Original reviewed suggestions/history or actual later event not retained.');
  if(!await page.locator('[data-savia-reply]').evaluateAll((nodes,reply)=>
    nodes.some(x=>x.getAttribute('data-savia-reply')===reply),prior.bankReply.reply))
   throw Error('Exact original bank reply not rendered in original-session follow-up.');
  const card=page.locator('article.inquiry-card').filter({has:page.getByText(original.message,{exact:true})});
  if(await card.count()!==1)throw Error('Ambiguous original inquiry card.');
  await card.getByText('Esperando tu respuesta',{exact:true}).waitFor();
  await card.getByLabel('Sugerencias del equipo',{exact:true}).waitFor();await card.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'01-actual-normal-clock-followup.png')});
  receipt.followupObserved=true;receipt.actualFollowupEvent=event;receipt.targetAfter=retained;
  receipt.observedAt=new Date().toISOString();receipt.actualSecondsAfterCompletion=event.at-completedEvent.at;
  receipt.sameOriginalSession=true;receipt.exactOriginalBankReplyRetained=true;receipt.suggestionsRetained=true;
 }catch(error){receipt.failure={name:error.name,message:error.message,stack:error.stack};process.exitCode=1;}
 finally{
  clearTimeout(deadlineTimer);
  try{if(page?.video())receipt.video=path.basename(await page.video().path());}catch{}
  await context?.close().catch(()=>{});await Promise.allSettled(tasks);await browser?.close().catch(()=>{});
  receipt.ownedContextsClosed=true;receipt.finishedAt=new Date().toISOString();receipt.durationMs=at();
  await fs.writeFile(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({followupObserved:receipt.followupObserved,apiWrites:receipt.apiWrites.length,
   failure:receipt.failure?.message||null,output:out}));
 }
}
