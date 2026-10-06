/** Mechanical native-message event validation, not semantic/hearing/UI acceptance. */
import assert from 'node:assert/strict';
export const PHRASES=Object.freeze({es:'bloquea mi tarjeta',pt:'bloqueie meu cartão'});
export function admitPost(route,body,language,budget){
  if(!body||typeof body!=='object'||!Object.hasOwn(PHRASES,language))return null;
  const keys=Object.keys(body).sort().join(',');
  if(route==='/api/cards/block'&&keys==='language,operation,product_reference'&&body.operation==='status'&&body.language===language&&typeof body.product_reference==='string'&&body.product_reference&&budget.status<2){budget.status++;return 'status';}
  if(route==='/api/voice/turn'&&keys==='fresh,language,message'&&body.message===PHRASES[language]&&body.language===language&&body.fresh===true&&budget.native<1){budget.native++;return 'native';}
  return null;
}
export function validateNativeEvents(events,language){
  assert(Array.isArray(events)&&events.length>=4);assert(Object.hasOwn(PHRASES,language));
  assert.equal(events[0].type,'start');assert.equal(events.at(-1).type,'complete');
  const allowed=new Set(['start','caption','audio','delegate','complete']);
  assert(events.every(e=>allowed.has(e.type)),'Unexpected/error/heard event is not accepted');
  assert.equal(events.filter(e=>e.type==='start').length,1);assert.equal(events.filter(e=>e.type==='complete').length,1);
  const start=events[0],complete=events.at(-1),delegates=events.filter(e=>e.type==='delegate');
  assert.equal(start.sample_rate,24000);assert.equal(typeof start.turn_id,'string');assert(start.turn_id);
  assert.equal(complete.turn_id,start.turn_id);assert.equal(delegates.length,1);assert.equal(delegates[0].request,PHRASES[language]);
  let bytes=0,audioChunks=0;
  for(const e of events){
    if(e.type==='audio'){
      assert.equal(typeof e.data,'string');assert(/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(e.data));
      const pcm=Buffer.from(e.data,'base64');assert(pcm.length>0&&pcm.length%2===0);assert.equal(pcm.toString('base64'),e.data);
      bytes+=pcm.length;audioChunks++;
    }
    if(e.type==='caption')assert.equal(typeof e.text,'string');
  }
  assert(bytes>0&&bytes<=9600000);assert.equal(complete.samples,bytes/2);assert.equal(typeof complete.text,'string');
  assert(!/\b(?:bloqueo\s+(?:completado|confirmado)|bloqueio\s+(?:conclu[ií]do|confirmado)|ya\s+(?:he\s+)?bloque|j[aá]\s+bloque|(?:tarjeta|cart[aã]o).{0,30}(?:fue|foi)\s+bloquead)/i.test(complete.text),'Unsupported completed-card claim in native caption');
  return {passed:true,exactDelegate:true,delegateRequest:delegates[0].request,terminalComplete:true,
    sampleRate:24000,samples:complete.samples,audioChunks,providerToolChoiceObservedThroughSourceBoundDelegate:true,
    caption:complete.text,unsupportedActionClaimsManualReviewRequired:true,
    audioPlayed:false,actualUIPlayedAck:false,asrQualified:false,microphoneQualified:false};
}
