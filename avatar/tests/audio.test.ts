import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';
import { base64Bytes, boundedVoiceHistory, pcm16FromFloat32, Pcm16Resampler, Pcm16Stream, readNdjson, speechSentences, splitSpeechText, wavFromPcm } from '../src/audio.ts';

const text = new TextEncoder();
const responseFrom = (chunks: Uint8Array[]) => new Response(new ReadableStream<Uint8Array>({
  start(controller) { for (const chunk of chunks) controller.enqueue(chunk); controller.close(); },
}));
const pcmSamples = (wav: Uint8Array) => {
  const view = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
  return Array.from({ length: (wav.length - 44) / 2 }, (_, index) => view.getInt16(44 + index * 2, true));
};

test('initial audio preserves every signed PCM16 value byte-for-byte through decoded replay frames', () => {
  const bytes = new Uint8Array(65536 * 2), view = new DataView(bytes.buffer);
  for (let i = 0; i < 65536; i++) view.setInt16(i * 2, i - 32768, true);
  const decoded = new Pcm16Stream().decode(bytes);
  assert.deepEqual(pcm16FromFloat32(decoded), bytes);
  const invalid = pcm16FromFloat32(new Float32Array([NaN, Infinity, -Infinity, 2, -2]));
  assert.deepEqual(Array.from({ length: 5 }, (_, i) => new DataView(invalid.buffer).getInt16(i * 2, true)), [0, 0, 0, 32767, -32768]);
});

test('WAV is mono signed PCM at the requested rate, with duration preserved across capture chunks', () => {
  const source = new Float32Array(48_000).fill(.25);
  const whole = wavFromPcm([source], 48_000);
  const fragmented = wavFromPcm([source.subarray(0,127), source.subarray(127,2049), source.subarray(2049)],48_000);
  assert.deepEqual(fragmented, whole);
  const view = new DataView(whole.buffer);
  assert.equal(new TextDecoder().decode(whole.subarray(0,4)),'RIFF');
  assert.equal(new TextDecoder().decode(whole.subarray(8,12)),'WAVE');
  assert.equal(view.getUint32(4,true),whole.length-8);
  assert.equal(view.getUint16(20,true),1);
  assert.equal(view.getUint16(22,true),1);
  assert.equal(view.getUint32(24,true),16_000);
  assert.equal(view.getUint32(28,true),32_000);
  assert.equal(view.getUint16(34,true),16);
  assert.equal(view.getUint32(40,true),32_000);
  assert.equal(pcmSamples(whole).length,16_000);
  assert.ok(pcmSamples(whole).every(sample=>Math.abs(sample-8192)<=1));
});

test('fractional 44.1kHz resampling weights interval edges rather than dropping them', () => {
  const source = new Float32Array([0,.25,.5,.75,.25,0,-.25,-.5,-.75]);
  const samples = pcmSamples(wavFromPcm([source],44_100));
  const interval=44_100/16_000;
  const expectedFirst=(.25+.5*(interval-2))/interval;
  assert.ok(Math.abs(samples[0]/32767-expectedFirst)<1/32767);
  assert.equal(samples.length,Math.floor(source.length/interval));
});

test('downsampling averages high-frequency energy; encoding clamps peaks and silences invalid samples', () => {
  assert.deepEqual(pcmSamples(wavFromPcm([new Float32Array([1,-1,1,-1,1,-1])],48_000)),[10922,-10922]);
  assert.deepEqual(pcmSamples(wavFromPcm([new Float32Array([-2,2,NaN,Infinity])],16_000)),[-32768,32767,0,0]);
  assert.equal(wavFromPcm([],48_000).length,44);
  for(const rate of [0,-1,NaN,Infinity]) assert.throws(()=>wavFromPcm([],rate),RangeError);
  assert.throws(()=>wavFromPcm([],48_000,0),RangeError);
});

test('base64 preserves binary data over the browser argument-size boundary', () => {
  const bytes=Uint8Array.from({length:75_000},(_,index)=>index%256);
  assert.deepEqual(new Uint8Array(Buffer.from(base64Bytes(bytes),'base64')),bytes);
});

test('continuous native PCM resampling preserves exact duration across 2048-sample blocks at common browser rates', () => {
  for (const rate of [16_000, 44_100, 48_000]) {
    const input = Float32Array.from({length:rate}, (_, index) => .3 * Math.sin(index * .07));
    const whole = new Pcm16Resampler(rate).encode(input);
    const stream = new Pcm16Resampler(rate), chunks:Uint8Array[] = [];
    for (let offset=0;offset<input.length;offset+=2048) chunks.push(stream.encode(input.subarray(offset,offset+2048)));
    const bytes = new Uint8Array(chunks.reduce((count,chunk)=>count+chunk.length,0)); let offset=0;
    for (const chunk of chunks) { bytes.set(chunk,offset); offset+=chunk.length; }
    assert.equal(bytes.length,32_000); assert.deepEqual(bytes,whole);
    const wav = wavFromPcm([input],rate).subarray(44);
    const a = new DataView(bytes.buffer), b = new DataView(wav.buffer,wav.byteOffset,wav.byteLength);
    for(let index=0;index<16_000;index++) assert.ok(Math.abs(a.getInt16(index*2,true)-b.getInt16(index*2,true))<=1);
  }
});

test('continuous native resampling keeps fractional edges and discards pre-mute carry when reset', () => {
  const encoder = new Pcm16Resampler(48_000);
  assert.equal(encoder.encode(new Float32Array([1,1])).length,0);
  const edge=encoder.encode(new Float32Array([-1])); assert.equal(new DataView(edge.buffer).getInt16(0,true),10922);
  encoder.encode(new Float32Array([1,1])); encoder.reset();
  const silence=encoder.encode(new Float32Array([0,0,0])); assert.equal(new DataView(silence.buffer).getInt16(0,true),0);
  const direct=new Pcm16Resampler(16_000).encode(new Float32Array([-2,2,NaN,Infinity]));
  assert.deepEqual(new Pcm16Stream().decode(direct), new Float32Array([-1,32767/32768,0,0]));
  for(const rate of [0,-1,NaN,Infinity]) assert.throws(()=>new Pcm16Resampler(rate),RangeError);
});

test('PCM stream preserves signed samples across one-byte boundaries and offset views', () => {
  const values=[-32768,-12345,-1,0,1,12345,32767];
  const bytes=new Uint8Array(values.length*2+4); const view=new DataView(bytes.buffer);
  values.forEach((value,index)=>view.setInt16(2+index*2,value,true));
  const decoder=new Pcm16Stream(); const decoded:number[]=[];
  for(const byte of bytes.subarray(2,bytes.length-2)) decoded.push(...decoder.decode(new Uint8Array([byte])));
  decoder.finish(); assert.deepEqual(decoded,values.map(value=>value/32768));
  const offsetDecoder=new Pcm16Stream(); assert.deepEqual([...offsetDecoder.decode(bytes.subarray(2,bytes.length-2))],decoded); offsetDecoder.finish();
});

test('PCM stream retains an unfinished sample through empty chunks and rejects truncated EOF', () => {
  const decoder=new Pcm16Stream(); assert.equal(decoder.decode(new Uint8Array([0])).length,0);
  assert.equal(decoder.decode(new Uint8Array()).length,0);
  assert.throws(()=>decoder.finish(),/middle of an audio sample/);
  assert.deepEqual([...decoder.decode(new Uint8Array([128]))],[-1]); decoder.finish();
});

test('speech batching drains coalesced sentences and prevents a short acknowledgement from blocking later audio', () => {
  const first=speechSentences('Yes.'); assert.deepEqual(first,{ready:[],pending:'Yes.'});
  const next=speechSentences(`${first.pending} We can start here. Then take one small step. Still typing`);
  assert.deepEqual(next,{ready:['Yes. We can start here.','Then take one small step.'],pending:'Still typing'});
  assert.deepEqual(speechSentences('The amount is 3.8 euros. We can review it.'),{ready:['The amount is 3.8 euros.','We can review it.'],pending:''});
});

test('speech request bounds preserve words and Unicode while splitting oversized sentences', () => {
  const input='This is one sentence with many useful words '.repeat(90).trim();
  const chunks=splitSpeechText(input); assert.ok(chunks.length>1); assert.ok(chunks.every(chunk=>chunk.length<=1200));
  assert.equal(chunks.join(' '),input);
  const token='a'.repeat(1199)+'🌿'+'b'.repeat(1200);
  const tokenChunks=splitSpeechText(token); assert.equal(tokenChunks.join(''),token); assert.ok(tokenChunks.every(chunk=>chunk.length<=1200));
  assert.ok(tokenChunks.every(chunk=>!/[\uD800-\uDBFF]$/.test(chunk)));
  assert.deepEqual(splitSpeechText('   '),[]);
});

test('voice history retains the latest bounded context without exceeding backend item or character limits', () => {
  const items=Array.from({length:20},(_,index)=>({role: index%2 ? 'assistant' as const : 'user' as const, content:`${index}: `+'x'.repeat(990)}));
  const history=boundedVoiceHistory(items); assert.ok(history.length<=10); assert.ok(history.reduce((sum,item)=>sum+item.content.length,0)<=8000);
  assert.deepEqual(history.at(-1),items.at(-1));
  assert.equal(boundedVoiceHistory([{role:'user',content:'x'.repeat(5000)}])[0].content.length,4000);
  assert.equal(boundedVoiceHistory(Array.from({length:12},()=>({role:'user',content:'short'}))).length,10);
});

test('NDJSON decodes UTF-8 at arbitrary byte boundaries, CRLF, blank lines, and EOF without a newline', async () => {
  const encoded=text.encode('\r\n{"type":"text","delta":"Hello 🌿"}\r\n\n{"type":"tool","name":"set_world"}');
  const response=responseFrom(Array.from(encoded,byte=>new Uint8Array([byte])));
  const events:Record<string,unknown>[]=[];
  await readNdjson(response,event=>events.push(event));
  assert.deepEqual(events,[{type:'text',delta:'Hello 🌿'},{type:'tool',name:'set_world'}]);
  assert.equal(response.body?.locked,false);
});

test('NDJSON limits a single event, allowing many small events coalesced into one large transport chunk', async () => {
  const encoded=text.encode(Array.from({length:5000},(_,index)=>JSON.stringify({type:'text',delta:`Event ${index}, keep the stream moving.`})).join('\n'));
  assert.ok(encoded.length>128_000);
  let count=0; await readNdjson(responseFrom([encoded]),()=>count++); assert.equal(count,5000);
  await assert.rejects(readNdjson(responseFrom([text.encode(`{"delta":"${'x'.repeat(128_001)}"}\n`)]),()=>{}),/exceeded its limit/);
});

test('NDJSON cancels and unlocks an upstream stream if a tool callback or parser fails', async () => {
  for(const callbackFailure of [false,true]) {
    let cancelled=false;
    const response=new Response(new ReadableStream<Uint8Array>({
      start(controller) { controller.enqueue(text.encode(callbackFailure ? '{"type":"tool"}\n' : '{broken}\n')); },
      cancel() { cancelled=true; },
    }));
    await assert.rejects(readNdjson(response,()=>{ if(callbackFailure) throw new Error('Tool rejected'); }));
    assert.equal(cancelled,true); assert.equal(response.body?.locked,false);
  }
});

test('NDJSON refuses primitive events, incomplete JSON, and malformed UTF-8', async () => {
  for(const input of ['null\n','[]\n','42\n','{"type":']) await assert.rejects(readNdjson(responseFrom([text.encode(input)]),()=>{}));
  await assert.rejects(readNdjson(responseFrom([new Uint8Array([123,34,120,34,58,34,255,34,125])]),()=>{}));
});

test('audio worklet transfers exact 2048-sample blocks without losing unusual input frame boundaries', () => {
  const sent:Float32Array[]=[];
  let Capture: new()=>{ process(inputs:Float32Array[][]):boolean };
  runInNewContext(readFileSync(new URL('../public/audio-capture.js',import.meta.url),'utf8'),{
    Float32Array,
    AudioWorkletProcessor:class { port={postMessage:(pcm:Float32Array,transfers:ArrayBuffer[])=>{sent.push(structuredClone(pcm,{transfer:transfers}));}}; },
    registerProcessor:(name:string,implementation:typeof Capture)=>{assert.equal(name,'voice-capture'); Capture=implementation;},
  });
  const capture=new Capture!();
  assert.equal(capture.process([]),true);
  const expected=Float32Array.from({length:8192},(_,index)=>(index%31)/31);
  let offset=0;
  for(const count of [128,777,4096,73,3118]) { assert.equal(capture.process([[expected.subarray(offset,offset+count)]]),true); offset+=count; }
  assert.equal(offset,expected.length); assert.equal(sent.length,4);
  assert.ok(sent.every(chunk=>chunk.length===2048));
  const actual=new Float32Array(8192); sent.forEach((chunk,index)=>actual.set(chunk,index*2048)); assert.deepEqual(actual,expected);
});
