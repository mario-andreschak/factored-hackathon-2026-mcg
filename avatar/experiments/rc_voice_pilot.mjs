import fs from 'node:fs/promises';
import {performance} from 'node:perf_hooks';
if (!process.argv.includes('--execute')) throw Error('Pass --execute for one paid native voice call.');
const base='http://127.0.0.1:43941';
const dir=new URL('../.local/rc-voice-pilot/',import.meta.url); await fs.mkdir(dir,{recursive:true});
if (await fs.access(new URL('report.json', dir)).then(() => true, () => false)) throw Error('The one-call pilot already has a report; reuse it.');
await fs.writeFile(new URL('started.json', dir), JSON.stringify({started_at:new Date().toISOString(),max_calls:1}), {flag:'wx'});
const config=await fetch(base+'/api/avatar/config'); const cookie=config.headers.getSetCookie()[0].split(';')[0];
const start=performance.now();
const res=await fetch(base+'/api/avatar/native-turn',{method:'POST',headers:{Origin:base,Cookie:cookie,'Content-Type':'application/json'},body:JSON.stringify({message:'Me preocupa un cargo que no reconozco. Quiero entenderlo antes de hacer algo.',avatar:'moss',locale:'es'}),signal:AbortSignal.timeout(45000)});
const reader=res.body.getReader(),decoder=new TextDecoder(); let carry='',pcm=[],complete=null,firstAudioMs=null,caption='';
while(true){const {done,value}=await reader.read();carry+=decoder.decode(value??new Uint8Array(),{stream:!done});const lines=carry.split('\n');carry=lines.pop();for(const line of lines){if(!line.trim())continue;const event=JSON.parse(line);if(event.type==='audio'){firstAudioMs??=Math.round(performance.now()-start);pcm.push(Buffer.from(event.data,'base64'));}if(event.type==='caption')caption=event.text;if(event.type==='complete')complete=event;if(event.type==='error')throw Error(event.code);}if(done)break;}
if(!complete||carry.trim())throw Error('native stream incomplete');const data=Buffer.concat(pcm);if(data.length/2!==complete.samples)throw Error('native sample mismatch');
const h=Buffer.alloc(44);h.write('RIFF');h.writeUInt32LE(data.length+36,4);h.write('WAVEfmt ',8);h.writeUInt32LE(16,16);h.writeUInt16LE(1,20);h.writeUInt16LE(1,22);h.writeUInt32LE(24000,24);h.writeUInt32LE(48000,28);h.writeUInt16LE(2,32);h.writeUInt16LE(16,34);h.write('data',36);h.writeUInt32LE(data.length,40);
await fs.writeFile(new URL('opening.wav',dir),Buffer.concat([h,data]),{flag:'wx'});
const report={schema:'savia-voice-typed-pilot/v1',recorded_at:new Date().toISOString(),http_status:res.status,actual_provider_calls:1,bank_calls:0,generic_flujo_calls:0,input:'fictional typed Spanish concern',physical_microphone:false,browser_playback:false,playback_ack_sent:false,sample_rate:24000,sample_rate_qualification:'assumed',first_audio_ms:firstAudioMs,completion_ms:Math.round(performance.now()-start),audio_seconds:complete.samples/24000,reply:complete.text,usage:complete.usage};
await fs.writeFile(new URL('report.json',dir),JSON.stringify(report,null,2),{flag:'wx'});console.log(JSON.stringify(report));
