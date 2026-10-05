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
import {captureReleaseAudio,captureBrowserCloneAudio} from './capture_savia_audio.mjs';

const contract={
 schema:'savia-integrated-native-journey/v1',
 intendedUI:'Savia portal assistant dialog with Eyes/Moss and Hablar con Savia',
 writes:{'/api/chat/messages':1,'/api/assistant/cases':1,'/api/voice/turn':2,'/api/voice/played':2,
  '/api/assistant/cases/[created]/resolve':1},
 maximumPartialTranscriptionRequests:6,
 preservedState:'existing informational inquiry remains; helpful closure only for created informational inquiry; no bank action, confirmation, or reset',
 input:'typed bank facts with voice off; existing fictional Spanish prerecorded microphone smalltalk; typed informational inquiry during foreground speech',
 output:'two actual native provider PCM WAVs, exact full-playback ACKs, unedited UI screenshots/video',
 physicalMicrophoneQualified:false,
 executionGate:'explicit root GO, frozen healthy corrected source/image, fresh private output directory',
};
const [mode,bindingPath,outputPath]=process.argv.slice(2);
if(mode!=='--execute'){
 if(!['--describe','--describe-continuation'].includes(mode))throw Error('Use --describe for preparation, or --execute after explicit root GO.');
 if(mode==='--describe-continuation'){
  contract.writes['/api/chat/messages']=0;contract.writes['/api/assistant/cases']=0;
  contract.input='same actual saved session/case3; existing bank history and suggestions; prerecorded mic foreground; normal UI helpful closure';
  contract.preservedState='retain all three cases; close only existing case3 informationally; no bank action, confirmation, new case, or reset';
  contract.input='same actual saved session/case3; existing bank history and suggestions; prerecorded mic foreground; normal UI helpful closure';
  contract.secondNativeOutput='verified informational closure, not narrated worker recommendations';
  contract.newWorkerTaskInThisRun=false;
 }
 console.log(JSON.stringify(contract,null,2));
}else{
 await execute(bindingPath,outputPath);
}

async function execute(bindingPath,outputPath){
 if(!bindingPath||!outputPath)throw Error('Private binding and fresh private output directory required.');
 const cfg=JSON.parse(await fs.readFile(bindingPath,'utf8'));
 const continuation=cfg.continuation_run===true;
 if(continuation&&cfg.continuation_root_go!==true)throw Error('New explicit continuation GO required.');
 let priorReceipt;
 if(continuation){
  priorReceipt=JSON.parse(await fs.readFile(cfg.resume_receipt_private,'utf8'));
  if(priorReceipt.sourceGitHead!==cfg.runtime?.git_head||priorReceipt.imageDigest!==cfg.runtime?.image_digest||
     priorReceipt.createdInquiry?.id!==cfg.existing_case_id||priorReceipt.baseUrl!==cfg.base_url)
   throw Error('Continuation must retain the actual same deployment/session/case.');
  contract.writes['/api/chat/messages']=0;contract.writes['/api/assistant/cases']=0;
  contract.secondNativeOutput='verified informational closure, not narrated worker recommendations';
  contract.newWorkerTaskInThisRun=false;
 }
 const runtime=cfg.runtime;
 if(cfg.generated_only!==true||cfg.root_go!==true||cfg.frozen_healthy!==true||cfg.successor_run!==true||
    cfg.intended_ui!=='savia-integrated-eyes'||!Number.isInteger(cfg.expected_existing_inquiries)||
    cfg.expected_existing_inquiries<2||!runtime||!/^sha256:[a-f0-9]{64}$/.test(runtime.image_digest||'')||
    !/^[a-f0-9]{40}$/.test(runtime.git_head||'')||
    ['6b3d6a224167c51103cfd95962d1220865147ba8','4a27f0e02ab8b1967af65725b85564cde1be8ac3'].includes(runtime.git_head))
  throw Error('Fresh corrected source/image and explicit root GO binding required; old standalone binding rejected.');
 const assets=runtime.served_ui;
 if(!assets||!Object.keys(assets).some(k=>/^assets\/index-.*\.js$/.test(k)))
  throw Error('Frozen current frontend asset manifest required.');
 if(!cfg.code||!cfg.profile||!cfg.base_url)throw Error('Private fictional form credentials required.');
 const origin=new URL(cfg.base_url).origin;
 if(cfg.base_url!==origin||!origin.startsWith('https://'))throw Error('Expected canonical HTTPS deployment origin.');
 const out=path.resolve(outputPath);
 if(!out.includes(`${path.sep}private${path.sep}`))throw Error('Capture must initially stay under private/.');
 await fs.mkdir(out,{recursive:false});
 const inputPath=path.resolve(cfg.foreground_wav||'private/submission-measurement-input/fictional-smalltalk-es.wav');
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
 const micPath=continuation?path.resolve(cfg.existing_padded_microphone):path.join(out,'fictional-microphone-with-silent-tail.wav');
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
 if(continuation){
  if(createHash('sha256').update(await fs.readFile(micPath)).digest('hex')!==createHash('sha256').update(paddedBytes).digest('hex'))
   throw Error('Continuation must reuse the unchanged existing padded microphone fixture.');
 }else await fs.writeFile(micPath,paddedBytes,{flag:'wx'});
 const frontendPackage=cfg.playwright_package_json||
  'C:/Users/Moe/.codex/worktrees/savia-final-day-rc/factored-hackathon-2026/frontend/package.json';
 const require=createRequire(path.resolve(frontendPackage));
 const playwright=require('playwright');
 const browser=await playwright.chromium.launch({headless:true,channel:cfg.channel||'msedge',args:[
  '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream',
  `--use-file-for-fake-audio-capture=${micPath}`,
 ]});
 const started=performance.now(),at=()=>Math.round(performance.now()-started);
 const receipt={...contract,startedAt:new Date().toISOString(),sourceGitHead:runtime.git_head,
  imageDigest:runtime.image_digest,baseUrl:origin,intendedUIAccepted:false,events:[],servedJS:[],
  existingInquiries:[],createdInquiry:null,bankReply:null,voiceTurns:[],played:[],requestCounts:{},completed:false,
  foregroundInput:{sha256:inputHash,utterance:'Tranquilo, respira hondo. Todo va a salir bien.',
   kind:'existing fictional synthetic WAV through actual browser microphone control',physicalMicrophoneQualified:false}};
 receipt.continuation=continuation;
 if(continuation)receipt.continuationInquiry={id:cfg.existing_case_id,newWorkerTask:false,
  priorPartialOverlap:{foregroundSpeakingAtMs:priorReceipt.foregroundSpeakingAtMs,teamSubmittedAtMs:priorReceipt.teamSubmittedAtMs}};
 const targetId=()=>receipt.createdInquiry?.id||receipt.continuationInquiry?.id;
 const tasks=[],nativeById=new Map();let failure,context,page,finalizeAudio;
 const rememberFailure=message=>{failure??=message;};
 const timer=setTimeout(()=>{rememberFailure('Journey exceeded bounded 180 second duration.');void browser.close();},180000);
 const ensure=()=>{if(failure)throw Error(failure);};
 const waitFor=async(test,timeout=60000)=>{
  const until=performance.now()+timeout;
  while(!test()){ensure();if(performance.now()>until)throw Error('Bounded observation wait expired.');await new Promise(r=>setTimeout(r,100));}
  ensure();
 };
 const observe=p=>{
  p.on('request',request=>{
   const route=new URL(request.url()).pathname;if(request.method()!=='POST'||!route.startsWith('/api/'))return;
   const key=targetId()&&route===`/api/assistant/cases/${targetId()}/resolve`
    ?'/api/assistant/cases/[created]/resolve':route;
   const limit=key==='/api/voice/transcribe'?contract.maximumPartialTranscriptionRequests:contract.writes[key];
   const count=receipt.requestCounts[key]=(receipt.requestCounts[key]||0)+1;
   if(!limit||count>limit){
    let message;try{message=request.postDataJSON()?.message;}catch{}
    receipt.unexpectedRequest={path:route,method:request.method(),atMs:at(),
     ...(typeof message==='string'?{fictionalMessage:message.slice(0,4000)}:{})};
    rememberFailure('Unexpected application POST or exceeded bounded write budget.');void browser.close();return;
   }
   if(route==='/api/voice/turn'){
    let data;try{data=request.postDataJSON();}catch{}
    const valid=count===1?data?.audio&&!data.result&&!data.message:data?.result&&!data.audio&&!data.message;
    if(!valid){rememberFailure('Unexpected native request kind or extra microphone turn.');void browser.close();}
    receipt.events.push({kind:count===1?'foreground-native-request':'canonical-team-native-request',atMs:at()});
   }else if(key==='/api/assistant/cases'){
    receipt.teamSubmittedAtMs=at();
   }else if(key==='/api/assistant/cases/[created]/resolve'){
    receipt.helpfulSubmittedAtMs=at();
   }
  });
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
      if(continuation)return; // Actual fetch clone supplies required native events and samples.
      const lines=(await response.text()).trim().split('\n').filter(Boolean).map(x=>JSON.parse(x));
      const first=lines[0],last=lines.at(-1);
      if(first?.type!=='start'||last?.type!=='complete'||first.turn_id!==last.turn_id||lines.some(x=>x.type==='error')){
       rememberFailure('Native stream did not complete.');return;
      }
      const turn={index:receipt.voiceTurns.length+1,samples:last.samples,sampleRate:first.sample_rate,
       transcript:last.text,heard:lines.find(x=>x.type==='heard')?.text||null,streamCompletedAtMs:at()};
      nativeById.set(first.turn_id,turn);receipt.voiceTurns.push(turn);
     }else if(route==='/api/voice/played'){
      const body=response.request().postDataJSON();
      await waitFor(()=>nativeById.has(body.turn_id),5000);
      const native=nativeById.get(body.turn_id);
      const ack={nativeIndex:native.index,httpStatus:response.status(),playedSamples:body.played_samples,
       complete:body.complete,exactSamples:body.played_samples===native.samples,atMs:event.atMs};
      receipt.played.push(ack);
      if(body.complete!==true||!ack.exactSamples||receipt.played.filter(x=>x.nativeIndex===native.index).length!==1)
       rememberFailure('Native full-playback receipt was inexact or duplicated.');
     }else if(route==='/api/chat/messages'&&response.request().method()==='POST'){
      const value=await response.json();receipt.bankReply={reply:value.reply,queries:value.queries,atMs:at()};
     }else if(route==='/api/assistant/cases'){
      const value=await response.json();
      if(response.request().method()==='POST')receipt.createdInquiry={id:value.id,atMs:at()};
      if(!receipt.existingInquiries.length&&response.request().method()==='GET')
       receipt.existingInquiries=(value.items||[]).map(x=>({id:x.id,state:x.state}));
      receipt.latestInquiries=value.items||[];
     }else if(route==='/api/chat/history'){
      receipt.restoredServerHistory=(await response.json()).messages||[];
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
  if(continuation)state=JSON.parse(await fs.readFile(cfg.resume_storage_state_private,'utf8'));
  else{
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
  page=await context.newPage();observe(page);
  finalizeAudio=continuation?await captureBrowserCloneAudio(page,path.join(out,'audio'),{
   onComplete:value=>{
    const turn={index:value.index,samples:value.samples,sampleRate:value.sampleRate,
     transcript:value.transcript,heard:value.heard,streamCompletedAtMs:at()};
    nativeById.set(value.turnId,turn);receipt.voiceTurns.push(turn);
   },onError:error=>{receipt.nativeCloneError=error;rememberFailure('Required native fetch clone failed.');}
  }):await captureReleaseAudio(page,path.join(out,'audio'));
  await page.goto(origin,{waitUntil:'networkidle'});
  await Promise.allSettled(tasks);ensure();
  if(!receipt.servedJS.some(x=>x.status===200&&assets[x.path.slice(1)]===x.sha256&&/^\/assets\/index-.*\.js$/.test(x.path)))
   throw Error('Served frontend bytes do not match frozen corrected manifest.');
  await page.getByRole('button',{name:'Movimientos',exact:true}).click();
  await page.locator('.transaction-row').filter({hasText:'Nébula Market'}).first().click();
  await page.getByRole('button',{name:'Revisar este cargo',exact:true}).click();
  await page.locator('.assistant-eyes [data-avatar="moss"]').waitFor();
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).waitFor();
  await waitFor(()=>receipt.existingInquiries.length===cfg.expected_existing_inquiries,10000);
  await page.locator('.assistant-stage').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'01-integrated-savia.png')});
  if(continuation){
   await waitFor(()=>receipt.restoredServerHistory?.some(x=>x.role==='assistant'&&x.text===priorReceipt.bankReply.reply),10000);
   receipt.bankReply={reply:priorReceipt.bankReply.reply,restoredSameSession:true,atMs:at()};
  }else{
  await page.getByLabel('Mensaje para el asistente',{exact:true}).fill('¿Qué comercio, fecha, monto y estado aparecen en este movimiento?');
  await page.getByRole('button',{name:'Enviar mensaje',exact:true}).click();
  await waitFor(()=>receipt.bankReply);
  }
  const bankReplyLocator=page.locator('[data-savia-reply]').filter({hasText:'Nébula Market'}).last();
  await page.waitForFunction(reply=>Array.from(document.querySelectorAll('[data-savia-reply]'))
   .some(x=>x.getAttribute('data-savia-reply')===reply),receipt.bankReply.reply,{timeout:10000});
  await bankReplyLocator.scrollIntoViewIfNeeded();
  receipt.bankReply.visibleExactDOMAtMs=at();
  await page.screenshot({path:path.join(out,'02-bank-facts-voice-off.png')});
  const existingTarget=continuation?receipt.latestInquiries?.find(x=>x.id===cfg.existing_case_id):null;
  if(continuation&&(!existingTarget||!['team_completed','awaiting_customer'].includes(existingTarget.state)||
     existingTarget.workers?.length!==2||!existingTarget.workers.every(x=>x.state==='completed')))
   throw Error('Existing target must have a completed real team and an available helpful control.');
  const inquiryMessage=continuation?existingTarget.message:cfg.successor_run
   ?'Todavía necesito orientación sobre el cargo de Nébula Market. Revisa conmigo qué puedo comparar en mis recibos y cuál es el siguiente paso para esta consulta informativa.'
   :'No reconozco el cargo de Nébula Market. Ayúdame a comparar el comercio con mis recibos y a saber cuál es el siguiente paso.';
  const targetCard=page.locator('.inquiry-card').filter({hasText:inquiryMessage}).first();
  if(!continuation){
   await page.getByText('Pedir ayuda a un equipo',{exact:true}).click();
   await page.getByLabel('¿Qué necesitas aclarar?',{exact:true}).fill(inquiryMessage);
  }
  await page.getByRole('button',{name:'Hablar con Savia',exact:true}).click();
  await page.getByRole('button',{name:'Terminar voz',exact:true}).waitFor();
  await page.locator('.assistant-eyes [data-avatar="moss"][data-phase="speaking"]').waitFor({timeout:60000});
  receipt.foregroundSpeakingAtMs=at();
  if(continuation)await targetCard.getByRole('button',{name:'Esta respuesta resolvió mi consulta',exact:true}).click();
  else await page.getByRole('button',{name:'Enviar consulta',exact:true}).click();
  await page.locator('.assistant-stage').scrollIntoViewIfNeeded();
  receipt.foregroundCapturedPhase=await page.locator('.assistant-eyes [data-avatar="moss"]').getAttribute('data-phase');
  receipt.foregroundCaptureAtMs=at();
  await page.screenshot({path:path.join(out,'03-native-foreground-speaking.png')});
  await page.locator('.assistant-stage').screenshot({path:path.join(out,'03-native-eyes-mic-detail.png')});
  await waitFor(()=>targetId()&&receipt.played.length===2);
  const created=receipt.latestInquiries?.find(x=>x.id===targetId());
  if(!created||created.state!==(continuation?'informational_resolved':'team_completed')||created.bank_authority!==false||created.informational_only!==true||
     created.workers?.length!==2||!created.workers.every(x=>x.state==='completed'))
   throw Error('Created inquiry did not reach actual two-worker informational completion.');
  receipt.preservedInquiryUpdates=receipt.existingInquiries.filter(x=>!continuation||x.id!==targetId()).map(prior=>{
   const current=receipt.latestInquiries.find(x=>x.id===prior.id);
   return {id:prior.id,priorState:prior.state,currentState:current?.state||null,
    ordinaryFollowupTransition:prior.state==='team_completed'&&current?.state==='awaiting_customer'};
  });
  if(!receipt.preservedInquiryUpdates.every(x=>x.currentState===x.priorState||x.ordinaryFollowupTransition))
   throw Error('Preserved inquiry disappeared or changed outside its normal follow-up transition.');
  if(receipt.lastCanonicalTeamVoice?.case_id!==created.id||receipt.lastCanonicalTeamVoice?.bank_authority!==false)
   throw Error('Team audio canonical update is not scoped to the created inquiry.');
  receipt.completedInquiry=created;
  receipt.overlap={...(continuation?{newWorkerTaskInThisRun:false,
   actualHelpfulStateChangeDuringForeground:receipt.helpfulSubmittedAtMs<receipt.played[0].atMs}:
   {teamSubmittedDuringForeground:receipt.teamSubmittedAtMs<receipt.played[0].atMs}),
   completedTeamAvailableBeforeForegroundPlayed:receipt.lastCanonicalTeamVoice.atMs<receipt.played[0].atMs,
   teamNativeAfterForegroundPlayed:receipt.events.find(x=>x.kind==='canonical-team-native-request')?.atMs>=receipt.played[0].atMs};
  if(!(continuation?receipt.overlap.actualHelpfulStateChangeDuringForeground:receipt.overlap.teamSubmittedDuringForeground)||!receipt.overlap.teamNativeAfterForegroundPlayed)
   throw Error('Actual foreground overlap and ordered team playback were not observed.');
  if(!receipt.overlap.completedTeamAvailableBeforeForegroundPlayed)
   receipt.queueQualificationLimitation='Team result arrived after foreground full playback; concurrent task was observed, but waiting for busy playback was not exercised.';
  const card=page.locator('.inquiry-card').filter({hasText:inquiryMessage}).first();
  await card.getByText(continuation?'Consulta informativa completada':'Respuesta disponible',{exact:true}).waitFor();await card.scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(out,'04-team-completed-native-played.png')});
  await new Promise(r=>setTimeout(r,4000));
  await page.getByRole('button',{name:'Terminar voz',exact:true}).click();
  if(!continuation)await card.getByRole('button',{name:'Esta respuesta resolvió mi consulta',exact:true}).click();
  await card.getByText('Consulta informativa completada',{exact:true}).waitFor();
  await page.screenshot({path:path.join(out,'05-helpful-informational-closure.png')});
  await page.getByRole('button',{name:'Empezar chat nuevo',exact:true}).click();
  await page.getByRole('button',{name:'Ver conversación anterior',exact:true}).waitFor();
  await page.screenshot({path:path.join(out,'06-new-chat-saved-inquiry.png')});
  await page.getByRole('button',{name:'Ver conversación anterior',exact:true}).click();
  await page.getByRole('button',{name:'Volver al chat actual',exact:true}).waitFor();
  if(!await page.locator('[data-savia-reply]').evaluateAll((nodes,reply)=>nodes.some(x=>x.getAttribute('data-savia-reply')===reply),receipt.bankReply.reply))
   throw Error('Exact bank reply was not restored in archived conversation.');
  await card.getByLabel('Sugerencias del equipo',{exact:true}).waitFor();
  await page.screenshot({path:path.join(out,'07-restored-context-saved-suggestions.png')});
  receipt.contextRestored=true;receipt.helpfulInformationalClosure=true;
  await Promise.allSettled(tasks);ensure();
  for(const [route,count]of Object.entries(contract.writes))if((receipt.requestCounts[route]||0)!==count)
   throw Error('Exact bounded workflow request counts do not match.');
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
  receipt.finishedAt=new Date().toISOString();receipt.durationMs=at();
  await fs.writeFile(path.join(out,'receipt.json'),JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});
  console.log(JSON.stringify({completed:receipt.completed,intendedUIAccepted:receipt.intendedUIAccepted,
   nativeFiles:receipt.nativeAudio?.turns.filter(x=>x.completed).length||0,fullPlayed:receipt.played.length,
   output:out,failure:receipt.failure||null}));
 }
}
