/** Supporting existing-case proof only. --describe makes no browser/network call.
 * --execute PRIVATE_NEW_GO_BINDING NEW_PRIVATE_DIR requires a reviewed successor.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
import {captureBrowserCloneAudio} from './capture_savia_audio.mjs';

const scope={schema:'savia-saved-recommendation-capture/v1',nativeResultStreams:1,fullPlayedAcks:1,
 bankChat:0,newCases:0,newWorkers:0,resolutions:0,asr:0,historyReset:0,
 input:'unchanged existing silent file-backed microphone; ordinary explicit Listen control on case2',
 output:'supplemental actual useful recommendation WAV, full ACK, unedited Eyes/results clip and context',
 frozenFilmOrDeckMutation:false,physicalMicrophoneQualified:false,executionHeldUntilNewRootGO:true};
const [mode,bindingPath,outputPath]=process.argv.slice(2);
if(mode==='--describe')console.log(JSON.stringify(scope,null,2));
else if(mode==='--execute')await execute();
else throw Error('Use --describe, or --execute PRIVATE_BINDING NEW_PRIVATE_DIR after new root GO.');

async function execute(){
 const cfg=JSON.parse(await fs.readFile(bindingPath,'utf8')),runtime=cfg.runtime;
 if(cfg.root_go!==true||cfg.saved_recommendations_run!==true||cfg.frozen_healthy!==true||
    cfg.generated_only!==true||cfg.expected_existing_inquiries!==3||
    cfg.target_case_id!=='i_e446f6501b32437ea21638f2a93b8a51'||!cfg.listen_button_name||
    !/^[a-f0-9]{40}$/.test(runtime?.git_head||'')||
    runtime.git_head==='9d77a7599128b668b0e34f9c2937eb40b6bd3824'||
    !/^sha256:[a-f0-9]{64}$/.test(runtime.image_digest||''))throw Error('Fresh reviewed successor and new once-only GO required.');
 const origin=new URL(cfg.base_url).origin;
 if(origin!==cfg.base_url||!origin.startsWith('https://')||!runtime.served_ui)throw Error('Canonical HTTPS origin and actual served asset manifest required.');
 const mic=path.resolve(cfg.silent_microphone_private),micBytes=await fs.readFile(mic);
 if(createHash('sha256').update(micBytes).digest('hex')!=='fd967467076ec933370ff8a661819ee7b6390dc2d5975c71f1e2d3d72743400b')
  throw Error('Exact unchanged existing silent microphone fixture required.');
 const out=path.resolve(outputPath);
 if(!out.includes(`${path.sep}private${path.sep}`))throw Error('Supporting capture must initially remain private.');
 await fs.mkdir(out,{recursive:false});
 const require=createRequire(path.resolve(cfg.playwright_package_json||
  'C:/Users/Moe/.codex/worktrees/savia-final-day-rc/factored-hackathon-2026/frontend/package.json'));
 const browser=await require('playwright').chromium.launch({headless:true,channel:'msedge',args:[
  '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',`--use-file-for-fake-audio-capture=${mic}`]});
 const viewport={width:1360,height:900},started=performance.now(),at=()=>Math.round(performance.now()-started);
 const receipt={...scope,startedAt:new Date().toISOString(),sourceGitHead:runtime.git_head,imageDigest:runtime.image_digest,
  targetCaseId:cfg.target_case_id,baseUrl:origin,productChecksPassed:false,events:[],servedJS:[],postCounts:{},played:[],
  optionalObservationErrors:[],nativeTurns:[],contextRetained:false};
 let failure,context,page,finalizeAudio,casesObservation=0,historyObservation=0;
 const tasks=[],nativeById=new Map();
 const fail=message=>{failure??=message;};
 const ensure=()=>{if(failure)throw Error(failure);};
 const waitFor=async(test,ms=45000)=>{const until=performance.now()+ms;while(!test()){
  ensure();if(performance.now()>until)throw Error('Bounded required observation expired.');await new Promise(r=>setTimeout(r,100));}ensure();};
 const timer=setTimeout(()=>{fail('Supporting capture exceeded90seconds.');void browser.close();},90000);
 try{
  context=await browser.newContext({viewport,locale:'es-CO',timezoneId:'America/Bogota',
   storageState:cfg.resume_storage_state_private,recordVideo:{dir:out,size:viewport}});
  await context.grantPermissions(['microphone'],{origin});page=await context.newPage();
  // Intercept before forwarding: an unexpected POST must not reach the application.
  await context.route('**/api/**',async intercepted=>{
   const request=intercepted.request();
   const route=new URL(request.url()).pathname;
   if(request.method()!=='POST'||!route.startsWith('/api/'))return intercepted.continue();
   const count=receipt.postCounts[route]=(receipt.postCounts[route]||0)+1;
   if(!['/api/voice/turn','/api/voice/played'].includes(route)||count>1){
    fail('Unexpected application write or duplicate native request.');
    await intercepted.abort();void browser.close();return;
   }
   if(route==='/api/voice/turn'){
    const body=request.postDataJSON();
    if(typeof body?.result!=='string'||body.audio||body.message){
     fail('Only the actual saved canonical result may be spoken.');
     await intercepted.abort();void browser.close();return;
    }
    receipt.actualNativeResult=body.result;receipt.nativeRequestedAtMs=at();
   }
   await intercepted.continue();
  });
  page.on('requestfailed',request=>receipt.events.push({kind:'requestfailed',method:request.method(),
   path:new URL(request.url()).pathname,failure:request.failure(),atMs:at()}));
  page.on('pageerror',error=>receipt.events.push({kind:'pageerror',name:error.name,message:error.message,atMs:at()}));
  page.on('console',message=>{if(message.type()==='error')receipt.events.push({kind:'console',text:message.text(),atMs:at()});});
  page.on('response',response=>{
   const route=new URL(response.url()).pathname,method=response.request().method();
   if(route.endsWith('.js'))tasks.push((async()=>{try{receipt.servedJS.push({path:route,status:response.status(),
    sha256:createHash('sha256').update(await response.body()).digest('hex')});}catch(error){fail(error.message);}})());
   if(!route.startsWith('/api/'))return;
   const event={path:route,method,status:response.status(),atMs:at()};receipt.events.push(event);
   // Optional transport completion never gates full PCM/ACK validation or browser close.
   void response.finished().catch(error=>receipt.optionalObservationErrors.push({path:route,method,message:error.message,atMs:at()}));
   tasks.push((async()=>{
    try{
     if(response.status()>=400){fail(`Required application HTTP failure: ${route}`);return;}
     if(response.status()===204)return;
     if(route==='/api/assistant/cases'){
      receipt.cases=(await response.json()).items||[];casesObservation++;
     }else if(route==='/api/chat/history'){
      receipt.history=(await response.json()).messages||[];historyObservation++;
     }
     else if(route==='/api/auth/me')receipt.actualSessionHTTP=response.status();
     else if(route==='/api/assistant/voice-update'){
      const value=await response.json();receipt.canonical={...value,
       caseId:new URL(response.url()).searchParams.get('case_id'),atMs:event.atMs};
     }else if(route==='/api/voice/played'){
      const body=response.request().postDataJSON();await waitFor(()=>nativeById.has(body.turn_id),5000);
      const native=nativeById.get(body.turn_id),ack={httpStatus:response.status(),complete:body.complete,
       samples:body.played_samples,exactSamples:body.played_samples===native.samples,turnTokenSHA256:
       createHash('sha256').update(body.turn_id).digest('hex'),atMs:event.atMs};receipt.played.push(ack);
      if(body.complete!==true||!ack.exactSamples)fail('Inexact native full-playback acknowledgement.');
     }
    }catch(error){
     receipt.optionalObservationErrors.push({path:route,method,name:error.name,message:error.message,
      stack:error.stack,requestFailure:response.request().failure(),atMs:at()});
     if(method!=='GET')fail(`Required POST validation failed: ${route}`);
    }
   })());
  });
  finalizeAudio=await captureBrowserCloneAudio(page,path.join(out,'audio'),{
   onComplete:value=>{const turn={...value,turnTokenSHA256:createHash('sha256').update(value.turnId).digest('hex'),
    completedAtMs:at()};nativeById.set(value.turnId,turn);delete turn.turnId;receipt.nativeTurns.push(turn);},
   onError:error=>{receipt.requiredNativeError=error;fail('Required native response.clone failed.');}});
  await page.goto(origin,{waitUntil:'networkidle'});await Promise.allSettled(tasks);ensure();
  if(!receipt.servedJS.some(x=>x.status===200&&/^\/assets\/index-.*\.js$/.test(x.path)&&runtime.served_ui[x.path.slice(1)]===x.sha256))
   throw Error('Actual served successor UI bytes do not match binding.');
  if(receipt.actualSessionHTTP!==200)throw Error('Original authenticated SID not valid.');
  await page.getByRole('button',{name:'Movimientos',exact:true}).click();
  await page.locator('.transaction-row').filter({hasText:'Nébula Market'}).first().click();
  await page.getByRole('button',{name:'Revisar este cargo',exact:true}).click();
  await waitFor(()=>receipt.cases?.length===3&&receipt.history?.length>0,20000);
  const target=receipt.cases.find(x=>x.id===cfg.target_case_id);
  if(!target||!['team_completed','awaiting_customer'].includes(target.state)||target.workers.length!==2||
    !target.workers.every(x=>x.state==='completed'&&x.suggestion)||target.bank_authority!==false)
   throw Error('Existing actual useful team result unavailable.');
  receipt.initialCaseStates=receipt.cases.map(x=>({id:x.id,state:x.state}));receipt.targetBefore=target;
  receipt.historyBefore=structuredClone(receipt.history);
  const bankReply=receipt.historyBefore.find(x=>x.role==='assistant'&&x.text?.includes('Nébula Market'));
  if(!bankReply)throw Error('Original grounded bank chat history is unavailable.');
  const exactBankReplyVisible=()=>page.locator('[data-savia-reply]').evaluateAll((nodes,reply)=>
   nodes.some(x=>x.getAttribute('data-savia-reply')===reply),bankReply.text);
  if(!await exactBankReplyVisible())throw Error('Original exact bank reply is not rendered.');
  const card=page.locator('.inquiry-card').filter({hasText:target.message}).first();
  await card.getByLabel('Sugerencias del equipo',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).click();
  await page.getByRole('button',{name:'Terminar voz',exact:true}).waitFor();
  await card.getByRole('button',{name:cfg.listen_button_name,exact:true}).click();receipt.listenClickedAtMs=at();
  await page.locator('.assistant-eyes [data-avatar="moss"][data-phase="speaking"]').waitFor({timeout:45000});
  receipt.speakingAtMs=at();await page.locator('.assistant-stage').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'01-useful-native-speaking.png')});
  await page.locator('.assistant-stage').screenshot({path:path.join(out,'02-eyes-mic-detail.png')});
  await waitFor(()=>receipt.nativeTurns.length===1&&receipt.played.length===1);
  if(receipt.canonical?.caseId!==cfg.target_case_id||receipt.canonical.bank_authority!==false||
    !['team_completed','awaiting_customer'].includes(receipt.canonical.inquiry_state)||
    receipt.actualNativeResult!==receipt.canonical.reply||
    !target.workers.every(x=>receipt.canonical.reply.includes(x.suggestion)))throw Error('Spoken source is not the exact existing completed-worker canonical reply.');
  await card.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'03-useful-team-full-played.png')});
  const beforeReloadCases=casesObservation,beforeReloadHistory=historyObservation;
  await page.reload({waitUntil:'networkidle'});
  await page.getByRole('button',{name:'Movimientos',exact:true}).click();
  await page.locator('.transaction-row').filter({hasText:'Nébula Market'}).first().click();
  await page.getByRole('button',{name:'Revisar este cargo',exact:true}).click();
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).waitFor();
  await waitFor(()=>casesObservation>beforeReloadCases&&historyObservation>beforeReloadHistory,20000);
  await new Promise(r=>setTimeout(r,3000));
  await Promise.allSettled(tasks);ensure();
  if(receipt.postCounts['/api/voice/turn']!==1||receipt.postCounts['/api/voice/played']!==1||
    Object.keys(receipt.postCounts).length!==2)throw Error('Supporting capture exceeded exact one-stream/ACK budget.');
  const retained=receipt.cases.find(x=>x.id===cfg.target_case_id);
  if(!retained||retained.state!==target.state||!receipt.initialCaseStates.every(x=>receipt.cases.some(y=>y.id===x.id&&y.state===x.state)))
   throw Error('Existing inquiry state changed during read-only supporting capture.');
  if(JSON.stringify(receipt.history)!==JSON.stringify(receipt.historyBefore)||!await exactBankReplyVisible()||
     JSON.stringify(retained.workers)!==JSON.stringify(target.workers))
   throw Error('Original chat history or completed team suggestions were not retained after reload.');
  receipt.historyAfter=structuredClone(receipt.history);receipt.exactBankReplyRetained=true;
  receipt.contextRetained=true;receipt.duplicatesAfterReload=0;receipt.targetAfter=retained;
  await page.locator('.inquiry-card').filter({hasText:target.message}).first().scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'04-saved-context-no-duplicate.png')});
  receipt.productChecksPassed=true;receipt.semanticReview='pending exact useful provider caption review';
 }catch(error){receipt.failure={name:error.name,message:error.message,stack:error.stack};process.exitCode=1;}
 finally{
  clearTimeout(timer);try{if(page?.video())receipt.video=path.basename(await page.video().path());}catch{}
  await context?.close().catch(()=>{});await Promise.allSettled(tasks);
  if(finalizeAudio)receipt.nativeAudio=await finalizeAudio();await browser.close().catch(()=>{});
  if(receipt.productChecksPassed&&receipt.nativeAudio?.turns.filter(x=>x.completed).length!==1){
   receipt.productChecksPassed=false;receipt.failure={message:'Exact actual native WAV missing.'};process.exitCode=1;
  }
  receipt.finishedAt=new Date().toISOString();receipt.durationMs=at();receipt.ownedContextsClosed=true;
  await fs.writeFile(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({productChecksPassed:receipt.productChecksPassed,nativeFiles:receipt.nativeAudio?.turns.filter(x=>x.completed).length||0,
   fullPlayed:receipt.played.length,failure:receipt.failure?.message||null,output:out}));
 }
}
