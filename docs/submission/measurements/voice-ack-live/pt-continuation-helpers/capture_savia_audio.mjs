/** Passive observation of actual integrated Savia native responses. No requests. */
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
function wav(pcm,rate){
 const h=Buffer.alloc(44);h.write('RIFF');h.writeUInt32LE(pcm.length+36,4);h.write('WAVEfmt ',8);
 h.writeUInt32LE(16,16);h.writeUInt16LE(1,20);h.writeUInt16LE(1,22);h.writeUInt32LE(rate,24);
 h.writeUInt32LE(rate*2,28);h.writeUInt16LE(2,32);h.writeUInt16LE(16,34);h.write('data',36);h.writeUInt32LE(pcm.length,40);
 return Buffer.concat([h,pcm]);
}
export async function captureReleaseAudio(page,outputDir){
 await mkdir(outputDir,{recursive:true});const pending=[],turns=[];let sequence=0;
 const observer=response=>{
  const route=new URL(response.url()).pathname;if(route!=='/api/voice/turn')return;
  const index=++sequence;
  pending.push((async()=>{
   const record={index,route,httpStatus:response.status(),completed:false,physicalMicrophoneQualified:false};turns.push(record);
   try{
    if(!response.ok())return;const bytes=await response.body();if(bytes.length>10*1024*1024)return;
    const events=bytes.toString('utf8').trim().split('\n').filter(Boolean).map(x=>JSON.parse(x));
    const first=events[0],last=events.at(-1);if(first?.type!=='start'||first.sample_rate!==24000||last?.type!=='complete'||last.turn_id!==first.turn_id||events.some(e=>e.type==='error'))return;
    const pcm=Buffer.concat(events.filter(e=>e.type==='audio').map(e=>Buffer.from(e.data,'base64')));
    if(!pcm.length||pcm.length%2||pcm.length>1440000*2||pcm.length/2!==last.samples)return;
    const audio=`native-${String(index).padStart(2,'0')}.wav`;await writeFile(path.join(outputDir,audio),wav(pcm,first.sample_rate),{flag:'wx'});
    Object.assign(record,{completed:true,audio,samples:last.samples,seconds:last.samples/first.sample_rate,sampleRate:first.sample_rate,
     sampleRateQualification:'actual native start event',transcript:last.text,providerCostUsd:null});
   }catch(error){record.captureFailed=true;record.captureError={name:error.name,message:String(error.message).slice(0,2000)};}
  })());
 };
 page.on('response',observer);
 return async()=>{page.off('response',observer);await Promise.allSettled(pending);
  const report={schema:'savia-integrated-native-audio-capture/v1',actualProviderResponses:true,playedReceiptQualifiedByThisObserver:false,turns:turns.sort((a,b)=>a.index-b.index)};
  await writeFile(path.join(outputDir,'native-audio.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});return report;
 };
}

/** Transparent clone of actual browser fetch responses; never issues a request. */
export async function captureBrowserCloneAudio(page,outputDir,{onComplete,onError}={}){
 await mkdir(outputDir,{recursive:true});const turns=[],pending=[];
 await page.exposeBinding('__recordSaviaNativeClone',async(_source,value)=>{
  if(value.stage==='start'){
   turns.push({index:value.index,route:'/api/voice/turn',httpStatus:value.status,completed:false,
    physicalMicrophoneQualified:false,transport:'actual browser fetch response.clone'});return;
  }
  const record=turns.find(x=>x.index===value.index);
  if(!record)return;
  const task=(async()=>{
   try{
    if(value.stage==='error')throw Error(value.message);
    if(value.status!==200||Buffer.byteLength(value.text)>10*1024*1024)throw Error('Invalid native clone response status/size.');
    const events=value.text.trim().split('\n').filter(Boolean).map(x=>JSON.parse(x));
    const first=events[0],last=events.at(-1);
    if(first?.type!=='start'||first.sample_rate!==24000||last?.type!=='complete'||last.turn_id!==first.turn_id||events.some(x=>x.type==='error'))
     throw Error('Actual native clone stream did not have exact start/complete events.');
    const pcm=Buffer.concat(events.filter(x=>x.type==='audio').map(x=>Buffer.from(x.data,'base64')));
    if(!pcm.length||pcm.length%2||pcm.length>1440000*2||pcm.length/2!==last.samples)throw Error('Native clone sample count mismatch.');
    const audio=`native-${String(value.index).padStart(2,'0')}.wav`;
    await writeFile(path.join(outputDir,audio),wav(pcm,first.sample_rate),{flag:'wx'});
    await writeFile(path.join(outputDir,audio.replace('.wav','.ndjson')),value.text,{flag:'wx'});
    Object.assign(record,{completed:true,audio,samples:last.samples,sampleRate:first.sample_rate,
     seconds:last.samples/first.sample_rate,transcript:last.text,providerCostUsd:null,eventCount:events.length});
    onComplete?.({index:value.index,turnId:first.turn_id,samples:last.samples,sampleRate:first.sample_rate,
     transcript:last.text,heard:events.find(x=>x.type==='heard')?.text||null});
   }catch(error){
    record.captureFailed=true;record.captureError={name:error.name,message:error.message,stack:error.stack};onError?.(record.captureError);
   }
  })();pending.push(task);await task;
 });
 await page.addInitScript(()=>{
  const original=window.fetch;let index=0;
  window.fetch=async function(...args){
   const response=await original.apply(this,args);let native=false;
   try{native=new URL(typeof args[0]==='string'?args[0]:args[0].url,location.href).pathname==='/api/voice/turn';}catch{}
   if(native){
    const current=++index,clone=response.clone(),status=response.status;
    void (async()=>{
     await window.__recordSaviaNativeClone({stage:'start',index:current,status});
     const reader=clone.body.getReader(),decoder=new TextDecoder();let text='',bytes=0;
     try{
      while(true){const {done,value}=await reader.read();if(done)break;bytes+=value.byteLength;
       if(bytes>10*1024*1024)throw Error('Native clone exceeds bounded response size.');text+=decoder.decode(value,{stream:true});}
      text+=decoder.decode();
      await window.__recordSaviaNativeClone({stage:'complete',index:current,status,text});
     }finally{reader.releaseLock();}
    })().catch(error=>window.__recordSaviaNativeClone({stage:'error',index:current,status,message:String(error.message)}).catch(()=>{}));
   }
   return response;
  };
 });
 return async()=>{
  await Promise.allSettled(pending);
  const report={schema:'savia-browser-clone-native-audio/v1',actualProviderResponses:turns.some(x=>x.completed),
   requestInjection:false,audioInjection:false,playedReceiptQualifiedByThisObserver:false,turns};
  await writeFile(path.join(outputDir,'native-audio.json'),JSON.stringify(report,null,2)+'\n',{flag:'wx'});return report;
 };
}
