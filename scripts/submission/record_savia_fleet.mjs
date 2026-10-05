/** One actual integrated Savia journey, opt-in execution only.
 * Preparation: node record_savia_native.mjs --describe
 * After root GO: node record_savia_native.mjs --execute PRIVATE_BINDING NEW_PRIVATE_DIR
 * The binding must identify the frozen source/image, current frontend asset hashes,
 * fictional customer credentials, and the preserved inquiry count. No model retries.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
import {captureBrowserCloneAudio} from './capture_savia_audio.mjs';

const contract={
 schema:'savia-fleet-native-customer-journey/v1',
 intendedUI:'Savia portal assistant dialog with Eyes/Moss and Hablar con Savia',
 writes:{'/api/chat/messages':1,'/api/assistant/cases':1,'/api/voice/turn':2,'/api/voice/played':2},
 maximumPartialTranscriptionRequests:6,
 preservedState:'preserve existing inquiries; one new reviewed fleet informational inquiry; no resolution, bank action or history reset',
 input:'typed bank facts with voice off; existing fictional Spanish prerecorded microphone smalltalk; typed informational inquiry during foreground speech',
 output:'two actual native PCM WAVs, exact full-playback ACKs, unedited UI, actual receiver review, reload and follow-up status; full100 needs separate joined fleet traces',
 physicalMicrophoneQualified:false,
 executionGate:'explicit root GO, frozen healthy corrected source/image, fresh private output directory',
};
const [mode,bindingPath,outputPath]=process.argv.slice(2);
if(mode==='--describe')console.log(JSON.stringify(contract,null,2));
else if(mode==='--execute')await execute(bindingPath,outputPath);
else throw Error('Use --describe, or --execute with new healthy fleet customer binding.');
async function execute(bindingPath,outputPath){
 if(!bindingPath||!outputPath)throw Error('Private binding and fresh private output directory required.');
 const cfg=JSON.parse(await fs.readFile(bindingPath,'utf8')),runtime=cfg.runtime;
 if(cfg.root_go!==true||cfg.fleet_customer_run!==true||cfg.generated_only!==true||cfg.frozen_healthy!==true||
    cfg.intended_ui!=='savia-integrated-eyes'||!Number.isInteger(cfg.expected_existing_inquiries)||
    cfg.expected_existing_inquiries<0||!/^sha256:[a-f0-9]{64}$/.test(runtime?.image_digest||'')||
    !/^[a-f0-9]{40}$/.test(runtime?.git_head||'')||
    ['7089ca7b63006a066477415aaf54a6932d21a9b2','9d77a7599128b668b0e34f9c2937eb40b6bd3824'].includes(runtime.git_head))
  throw Error('New healthy fleet customer source/image and current root GO required.');
 const maxDurationMs=cfg.maximum_duration_ms??180000;
 if(!Number.isInteger(maxDurationMs)||maxDurationMs<60000||maxDurationMs>300000)
  throw Error('Explicit bounded capture duration must be 60–300 seconds.');
 const assets=runtime.served_ui;
 if(!assets||!Object.keys(assets).some(k=>/^assets\/index-.*\.js$/.test(k)))
  throw Error('Frozen current frontend asset manifest required.');
 if(!cfg.code||!cfg.profile||!cfg.base_url)throw Error('Private fictional form credentials required.');
 const origin=new URL(cfg.base_url).origin;
 if(cfg.base_url!==origin||!origin.startsWith('https://'))throw Error('Expected canonical HTTPS deployment origin.');
 const out=path.resolve(outputPath);
 if(!out.includes(`${path.sep}private${path.sep}`))throw Error('Capture must initially stay under private/.');
 await fs.mkdir(out,{recursive:false});
 if(!cfg.foreground_wav||!cfg.existing_padded_microphone)
  throw Error('Private paths to the reviewed existing foreground fixture and padded microphone are required.');
 const inputPath=path.resolve(cfg.foreground_wav);
 const input=await fs.readFile(inputPath);
 const inputHash=createHash('sha256').update(input).digest('hex');
 if(inputHash!=='3956bc585e5bac204010593ea5ae37182ac47828d034ffcb36f8e8daca481d6c')
  throw Error('Expected reviewed existing fictional public Spanish input fixture.');
 let inputPCM;
 for(let offset=12;offset+8<=input.length;){
  const size=input.readUInt32LE(offset+4),kind=input.toString('ascii',offset,offset+4);
  if(offset+8+size>input.length)throw Error('Invalid existing microphone fixture.');
  if(kind==='fmt '&&(input.readUInt16LE(offset+8)!==1||input.readUInt16LE(offset+10)!==1||
     input.readUInt32LE(offset+12)!==24000||input.readUInt16LE(offset+22)!==16))
   throw Error('Expected mono PCM16 24k existing input.');
  if(kind==='data')inputPCM=input.subarray(offset+8,offset+8+size);
  offset+=8+size+(size%2);
 }
 if(!inputPCM?.length)throw Error('Existing microphone fixture has no PCM samples.');
 const micPath=path.resolve(cfg.existing_padded_microphone);
 const pcm=Buffer.alloc(48000*2*180),header=Buffer.alloc(44);
 // Reuse existing samples at 48k, with a short lead-in and silence for the rest of this bounded run.
 for(let i=0;i<inputPCM.length/2;i++){
  const sample=inputPCM.readInt16LE(i*2),position=(14400+i*2)*2;
  pcm.writeInt16LE(sample,position);pcm.writeInt16LE(sample,position+2);
 }
 header.write('RIFF');header.writeUInt32LE(pcm.length+36,4);header.write('WAVEfmt ',8);
 header.writeUInt32LE(16,16);header.writeUInt16LE(1,20);header.writeUInt16LE(1,22);
 header.writeUInt32LE(48000,24);header.writeUInt32LE(96000,28);header.writeUInt16LE(2,32);
 header.writeUInt16LE(16,34);header.write('data',36);header.writeUInt32LE(pcm.length,40);
 const paddedBytes=Buffer.concat([header,pcm]);
 if(createHash('sha256').update(await fs.readFile(micPath)).digest('hex')!==createHash('sha256').update(paddedBytes).digest('hex'))
  throw Error('Reuse the unchanged existing padded fictional microphone fixture.');
 const frontendPackage=cfg.playwright_package_json||'frontend/package.json';
 const require=createRequire(path.resolve(frontendPackage));
 const playwright=require('playwright');
 const browser=await playwright.chromium.launch({headless:true,channel:cfg.channel||'msedge',args:[
  '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
  `--use-file-for-fake-audio-capture=${micPath}%noloop`,
 ]});
 const started=performance.now(),at=()=>Math.round(performance.now()-started);
 const receipt={...contract,startedAt:new Date().toISOString(),sourceGitHead:runtime.git_head,
  imageDigest:runtime.image_digest,baseUrl:origin,intendedUIAccepted:false,events:[],servedJS:[],
  existingInquiries:[],createdInquiry:null,bankReply:null,voiceTurns:[],played:[],requestCounts:{},completed:false,
  foregroundInput:{sha256:inputHash,utterance:'Tranquilo, respira hondo. Todo va a salir bien.',
   kind:'existing fictional synthetic WAV through actual browser microphone control',filePlaybackLoop:false,physicalMicrophoneQualified:false}};
 receipt.fullFleetCountVerified=false;receipt.fullFleetCountScope='separate runtime root/child traces required';
 const targetId=()=>receipt.createdInquiry?.id;
 const tasks=[],nativeById=new Map();let failure,context,page,finalizeAudio;
 let progressWrite=Promise.resolve();
 const saveProgress=()=>{
  const snapshot={schema:'savia-fleet-capture-private-progress/v1',startedAt:receipt.startedAt,
   updatedAt:new Date().toISOString(),sourceGitHead:receipt.sourceGitHead,imageDigest:receipt.imageDigest,
   baseUrl:origin,actualIntake:receipt.actualIntake||null,createdInquiry:receipt.createdInquiry||null,
   teamSubmittedAtMs:receipt.teamSubmittedAtMs||null};
  progressWrite=progressWrite.then(()=>fs.writeFile(path.join(out,'capture-progress-private.json'),JSON.stringify(snapshot,null,2)+'\n'));
  tasks.push(progressWrite.catch(error=>rememberFailure(error.message)));
 };
 const rememberFailure=message=>{failure??=message;};
 const timer=setTimeout(()=>{rememberFailure('Journey exceeded configured bounded duration.');void browser.close();},maxDurationMs);
 const ensure=()=>{if(failure)throw Error(failure);};
 const waitFor=async(test,timeout=60000)=>{
  const until=performance.now()+timeout;
  while(!test()){ensure();if(performance.now()>until)throw Error('Bounded observation wait expired.');await new Promise(r=>setTimeout(r,100));}
  ensure();
 };
 const observe=async p=>{
  await context.route('**/api/**',async intercepted=>{
   const request=intercepted.request(),route=new URL(request.url()).pathname;
   if(request.method()!=='POST'||!route.startsWith('/api/'))return intercepted.continue();
   const limit=route==='/api/voice/transcribe'?contract.maximumPartialTranscriptionRequests:contract.writes[route];
   const count=receipt.requestCounts[route]=(receipt.requestCounts[route]||0)+1;
   if(!limit||count>limit){
    receipt.unexpectedRequest={path:route,method:request.method(),atMs:at()};
    rememberFailure('Unexpected application POST or exceeded bounded budget.');
    await intercepted.abort();void browser.close();return;
   }
   if(route==='/api/voice/turn'){
    const data=request.postDataJSON();
    const valid=count===1?data?.audio&&!data.result&&!data.message:data?.result&&!data.audio&&!data.message;
    if(!valid){rememberFailure('Unexpected native request kind.');await intercepted.abort();void browser.close();return;}
    receipt.events.push({kind:count===1?'foreground-native-request':'canonical-team-native-request',atMs:at()});
    if(count===2)receipt.actualNativeResult=data.result;
   }else if(route==='/api/chat/messages')receipt.actualChatInput=request.postDataJSON();
   else if(route==='/api/assistant/cases'){
    receipt.teamSubmittedAtMs=at();receipt.actualIntake=request.postDataJSON();
    if(receipt.actualIntake.message!==cfg.inquiry_message||receipt.actualIntake.language!=='es'||
       !/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(receipt.actualIntake.request_id||'')){
     rememberFailure('Ordinary inquiry payload or stable UI request UUID differs from approved question.');
     await intercepted.abort();void browser.close();return;
    }
    saveProgress();
   }
   await intercepted.continue();
  }).catch(error=>rememberFailure(error.message));
  p.on('requestfailed',request=>receipt.events.push({kind:'request-failed',method:request.method(),
   path:new URL(request.url()).pathname,error:request.failure(),atMs:at()}));
  p.on('pageerror',error=>receipt.events.push({kind:'page-error',name:error.name,message:error.message,atMs:at()}));
  p.on('console',message=>{if(message.type()==='error')receipt.events.push({kind:'console-error',text:message.text(),atMs:at()});});
  p.on('response',response=>{
   const route=new URL(response.url()).pathname;
   if(route.endsWith('.js'))tasks.push((async()=>{
    try{receipt.servedJS.push({path:route,status:response.status(),sha256:createHash('sha256').update(await response.body()).digest('hex')});}
    catch{rememberFailure('Could not hash served JavaScript bytes.');}
   })());
   if(!route.startsWith('/api/'))return;
   const event={method:response.request().method(),path:route.replace(/i_[a-f0-9]{32}/g,'[fictional-inquiry]'),status:response.status(),atMs:at()};
   receipt.events.push(event);
   void response.finished().then(error=>{if(error)receipt.events.push({kind:'response-finished-error',
    path:route,method:response.request().method(),message:String(error.message),atMs:at()});}).catch(error=>{
    receipt.events.push({kind:'response-finished-error',path:route,message:String(error.message),atMs:at()});
   });
   tasks.push((async()=>{
    try{
     if(response.status()>=400){rememberFailure('Application request failed; no retry authorized.');return;}
     if(response.status()===204)return;
     if(route==='/api/voice/turn'){
      return; // Required PCM and stream events come from actual browser response.clone.
     }else if(route==='/api/voice/played'){
      const body=response.request().postDataJSON();
      await waitFor(()=>nativeById.has(body.turn_id),5000);
      const native=nativeById.get(body.turn_id);
      const ack={nativeIndex:native.index,httpStatus:response.status(),playedSamples:body.played_samples,
       turnTokenSHA256:createHash('sha256').update(body.turn_id).digest('hex'),
       complete:body.complete,exactSamples:body.played_samples===native.samples,atMs:event.atMs};
      receipt.played.push(ack);
      if(body.complete!==true||!ack.exactSamples||receipt.played.filter(x=>x.nativeIndex===native.index).length!==1)
       rememberFailure('Native full-playback receipt was inexact or duplicated.');
     }else if(route==='/api/chat/messages'&&response.request().method()==='POST'){
      const value=await response.json();receipt.bankReply={reply:value.reply,queries:value.queries,atMs:at()};
     }else if(route==='/api/assistant/cases'){
      const value=await response.json();
      if(response.request().method()==='POST'){
       receipt.createdInquiry={id:value.id,atMs:at()};saveProgress();
      }
      if(!receipt.initialCasesObserved&&response.request().method()==='GET'){
       receipt.existingInquiries=(value.items||[]).map(x=>({id:x.id,state:x.state}));receipt.initialCasesObserved=true;
      }
      receipt.latestInquiries=value.items||[];receipt.casesObservations=(receipt.casesObservations||0)+1;
      const working=receipt.latestInquiries.find(x=>x.id===targetId()&&x.state==='team_working');
      if(working)receipt.firstWorkingObservedAtMs??=event.atMs;
     }else if(route==='/api/chat/history'){
      receipt.restoredServerHistory=(await response.json()).messages||[];receipt.historyObservations=(receipt.historyObservations||0)+1;
     }else if(route==='/api/assistant/voice-update'){
      const value=await response.json();
      if(value?.reply)receipt.lastCanonicalTeamVoice={...value,
       case_id:new URL(response.url()).searchParams.get('case_id'),atMs:event.atMs};
     }
    }catch(error){
     receipt.validationErrors??=[];
     const method=response.request().method();
     receipt.validationErrors.push({path:route,method,status:response.status(),atMs:at(),
      name:error.name,message:String(error.message).slice(0,2000),stack:String(error.stack).slice(0,4000),
      requestFailure:response.request().failure(),fatal:method!=='GET'});
     if(method!=='GET')rememberFailure('Could not validate required observed application response.');
    }
   })());
  });
 };
 try{
  // Credentials stay in an unrecorded browser context; both logins use real UI forms.
  let state;
  {
  const entry=await browser.newContext({viewport:{width:1360,height:900},locale:'es-CO'});
  const entryPage=await entry.newPage();
  const profilesPromise=entryPage.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/profiles');
  await entryPage.goto(origin,{waitUntil:'domcontentloaded'});
  if(cfg.gateway){
   await entryPage.getByLabel(cfg.gateway.label,{exact:true}).fill(cfg.gateway.code);
   await entryPage.getByRole('button',{name:cfg.gateway.button,exact:true}).click();
  }
  const profiles=await (await profilesPromise).json();
  const profile=profiles.profiles?.find(x=>x.id===cfg.profile);
  if(!profile)throw Error('Configured fictional profile absent from actual served form.');
  await entryPage.getByRole('group',{name:'Elige un perfil de demostración',exact:true})
   .getByRole('button').filter({hasText:profile.alias}).click();
  await entryPage.getByLabel('Código de acceso',{exact:true}).fill(cfg.code);
  const login=entryPage.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/login'&&r.request().method()==='POST');
  await entryPage.getByRole('button',{name:'Entrar a mi banca',exact:true}).click();
  if((await login).status()!==200)throw Error('Actual customer form login failed.');
  state=await entry.storageState();await entry.close();
  }
  const viewport={width:1360,height:900};
  context=await browser.newContext({viewport,recordVideo:{dir:out,size:viewport},locale:'es-CO',
   timezoneId:'America/Bogota',storageState:state});
  await context.storageState({path:path.join(out,'browser-state-private.json')});
  await context.grantPermissions(['microphone'],{origin});
  page=await context.newPage();await observe(page);
  finalizeAudio=await captureBrowserCloneAudio(page,path.join(out,'audio'),{
   onComplete:value=>{
    const turn={index:value.index,samples:value.samples,sampleRate:value.sampleRate,
     turnTokenSHA256:createHash('sha256').update(value.turnId).digest('hex'),
     transcript:value.transcript,heard:value.heard,streamCompletedAtMs:at()};
    nativeById.set(value.turnId,turn);receipt.voiceTurns.push(turn);
   },onError:error=>{receipt.nativeCloneError=error;rememberFailure('Required native fetch clone failed.');}
  });
  await page.goto(origin,{waitUntil:'networkidle'});
  await Promise.allSettled(tasks);ensure();
  if(!receipt.servedJS.some(x=>x.status===200&&assets[x.path.slice(1)]===x.sha256&&/^\/assets\/index-.*\.js$/.test(x.path)))
   throw Error('Served frontend bytes do not match frozen corrected manifest.');
  await page.getByRole('button',{name:'Movimientos',exact:true}).click();
  await page.locator('.transaction-row').filter({hasText:'Nébula Market'}).first().click();
  await page.getByRole('button',{name:'Revisar este cargo',exact:true}).click();
  await page.locator('.assistant-eyes [data-avatar="moss"]').waitFor();
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).waitFor();
  await waitFor(()=>receipt.initialCasesObserved&&receipt.existingInquiries.length===cfg.expected_existing_inquiries,20000);
  await page.locator('.assistant-stage').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'01-integrated-savia.png')});
  await waitFor(()=>receipt.historyObservations>0,20000);
  receipt.originalHistory=structuredClone(receipt.restoredServerHistory);
  await page.getByLabel('Mensaje para el asistente',{exact:true}).fill('¿Qué comercio, fecha, monto y estado aparecen en este movimiento?');
  await page.getByRole('button',{name:'Enviar mensaje',exact:true}).click();await waitFor(()=>receipt.bankReply);
  await page.waitForFunction(reply=>Array.from(document.querySelectorAll('[data-savia-reply]'))
   .some(x=>x.getAttribute('data-savia-reply')===reply),receipt.bankReply.reply,{timeout:10000});
  receipt.bankReply.visibleExactDOMAtMs=at();
  await page.screenshot({path:path.join(out,'02-bank-facts-voice-off.png')});
  const inquiryMessage=cfg.inquiry_message;
  if(typeof inquiryMessage!=='string'||!inquiryMessage.trim())throw Error('Approved inquiry question required.');
  await page.getByText('Pedir ayuda a un equipo',{exact:true}).click();
  await page.getByLabel('¿Qué necesitas aclarar?',{exact:true}).fill(inquiryMessage);
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).click();
  await page.getByRole('button',{name:'Terminar voz',exact:true}).waitFor();
  await page.getByRole('button',{name:'Enviar consulta',exact:true}).click();
  await page.locator('.assistant-eyes [data-avatar="moss"][data-phase="speaking"]').waitFor({timeout:60000});
  receipt.foregroundSpeakingAtMs=at();await page.locator('.assistant-stage').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'03-native-foreground-speaking.png')});
  await page.locator('.assistant-stage').screenshot({path:path.join(out,'03-native-eyes-mic-detail.png')});
  await waitFor(()=>targetId()&&receipt.played.length===2,Math.max(60000,maxDurationMs-at()-15000));
  const created=receipt.latestInquiries?.find(x=>x.id===targetId());
  if(!created||!['team_completed','awaiting_customer'].includes(created.state)||created.bank_authority!==false||
     created.informational_only!==true||created.execution?.mode!=='recovered_fleet'||
     created.execution.review_status!=='verified'||created.execution.count_scope!=='root_review_subset'||
     !created.workers.length||!created.workers.every(x=>x.state==='completed'&&x.suggestion))
   throw Error('Actual reviewed fleet result unavailable; no fallback can qualify this receiver run.');
  if(receipt.lastCanonicalTeamVoice?.case_id!==created.id||receipt.lastCanonicalTeamVoice.bank_authority!==false||
     receipt.actualNativeResult!==receipt.lastCanonicalTeamVoice.reply||
     !created.workers.every(x=>receipt.actualNativeResult.includes(x.suggestion)))
   throw Error('Second native turn was not the exact actual reviewed canonical guidance.');
  receipt.completedInquiry=structuredClone(created);
  receipt.overlap={inquirySubmittedBeforeForegroundAck:receipt.teamSubmittedAtMs<receipt.played[0].atMs,
   actualWorkingObservedBeforeForegroundAck:typeof receipt.firstWorkingObservedAtMs==='number'&&receipt.firstWorkingObservedAtMs<receipt.played[0].atMs,
   completedResultNativeAfterForegroundAck:receipt.events.find(x=>x.kind==='canonical-team-native-request')?.atMs>=receipt.played[0].atMs};
  if(!receipt.overlap.inquirySubmittedBeforeForegroundAck||!receipt.overlap.completedResultNativeAfterForegroundAck)
   throw Error('Foreground request/result ordering was not observed.');
  if(!receipt.overlap.actualWorkingObservedBeforeForegroundAck)
   receipt.overlapLimitation='Submission during foreground is observed; actual running team overlap is not qualified without joined runtime timestamps.';
  const card=page.locator('article.inquiry-card').filter({has:page.getByText(inquiryMessage,{exact:true})});
  if(await card.count()!==1)throw Error('Ambiguous actual inquiry card.');
  await card.getByLabel('Sugerencias del equipo',{exact:true}).waitFor();await card.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'04-reviewed-team-native-played.png')});
  await page.getByRole('button',{name:'Terminar voz',exact:true}).click();
  const originalHistory=receipt.originalHistory.map(x=>({role:x.role,text:x.text}));
  const historyExpected=[...originalHistory,{role:'user',text:receipt.actualChatInput.message},
   {role:'assistant',text:receipt.bankReply.reply}];
  const caseReads=receipt.casesObservations,historyReads=receipt.historyObservations;
  await page.reload({waitUntil:'networkidle'});
  await page.getByRole('button',{name:'Movimientos',exact:true}).click();
  await page.locator('.transaction-row').filter({hasText:'Nébula Market'}).first().click();
  await page.getByRole('button',{name:'Revisar este cargo',exact:true}).click();
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).waitFor();
  await waitFor(()=>receipt.casesObservations>caseReads&&receipt.historyObservations>historyReads,20000);
  const retained=receipt.latestInquiries.find(x=>x.id===targetId());
  if(!retained||!['team_completed','awaiting_customer'].includes(retained.state)||
     retained.execution?.review_status!=='verified'||JSON.stringify(retained.workers)!==JSON.stringify(created.workers)||
     JSON.stringify(receipt.restoredServerHistory.map(x=>({role:x.role,text:x.text})))!==JSON.stringify(historyExpected)||
     !receipt.existingInquiries.every(x=>receipt.latestInquiries.some(y=>x.id===y.id&&x.state===y.state)))
   throw Error('Actual saved reviewed result or original case/chat context not retained after reload.');
  if(!await page.locator('[data-savia-reply]').evaluateAll((nodes,reply)=>
    nodes.some(x=>x.getAttribute('data-savia-reply')===reply),receipt.bankReply.reply))
   throw Error('Exact original grounded bank reply not rendered after reload.');
  await card.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'05-reloaded-review-followup.png')});
  receipt.contextRestored=true;receipt.followup={state:retained.state,nextCheckAt:retained.next_check_at,
   nextStep:retained.next_step,actualEvents:retained.events,
   scheduled:typeof retained.next_check_at==='number',normalClockFollowupObserved:retained.state==='awaiting_customer'};
  if(!receipt.followup.scheduled)throw Error('Actual reviewed inquiry follow-up is not scheduled.');
  await new Promise(r=>setTimeout(r,2000));await Promise.allSettled(tasks);ensure();
  for(const [route,count]of Object.entries(contract.writes))if((receipt.requestCounts[route]||0)!==count)
   throw Error('Exact bounded workflow request counts do not match.');
  if(receipt.latestInquiries.length!==cfg.expected_existing_inquiries+1)throw Error('Unexpected additional inquiry.');
  receipt.semanticReview='pending review of actual bank reply and both native transcripts';
  receipt.intendedUIAccepted=true;receipt.completed=true;
 }catch(error){
  receipt.failure=error.message;process.exitCode=1;
 }finally{
  clearTimeout(timer);
  try{if(page?.video())receipt.video=path.basename(await page.video().path());}catch{}
  await context?.close().catch(()=>{});
  await Promise.allSettled(tasks);
  if(finalizeAudio)receipt.nativeAudio=await finalizeAudio();
  if(receipt.completed&&receipt.nativeAudio?.turns.filter(x=>x.completed).length!==2){
   receipt.completed=false;receipt.intendedUIAccepted=false;
   receipt.failure='Two exact actual native WAVs were not captured.';process.exitCode=1;
  }
  await browser.close().catch(()=>{});
  receipt.ownedContextsClosed=true;
  receipt.finishedAt=new Date().toISOString();receipt.durationMs=at();
  await fs.writeFile(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({completed:receipt.completed,intendedUIAccepted:receipt.intendedUIAccepted,
   nativeFiles:receipt.nativeAudio?.turns.filter(x=>x.completed).length||0,fullPlayed:receipt.played.length,
   output:out,failure:receipt.failure||null}));
 }
}
